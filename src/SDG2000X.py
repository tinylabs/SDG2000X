#!/bin/env python3
#
# Signal generator class
#
from typing import Literal, Self
import pyvisa
import time
import logging
import numpy as np
import Waveform as wf
import matplotlib.pyplot as plt

class Signal:
    '''
    Represent a real signal to run on the siggen.
    Quantize a continuous waveform so we can upload it
    to siggen. Supports DDS and TARB
    '''
    TYPE = Literal['DDS', 'TARB']
    DDS_LENGTH = int(2**14)
    TARB_LENGTH = int(8e6)
    TARB_MAX_SRATE = 75e6
    MIN_MAX = [-32768, 32767]
    
    '''
    Wrapper for generic waveforms with specific to SDG2000X
    '''
    def __init__ (self,
                  wave : wf.WaveformBase,
                  amplitude : float,
                  channel : int,
                  offset : float = 0.0,
                  period : float = None,
                  name : str = None,
                  wavetype : TYPE = 'DDS',
                  ) -> None:

        # Save variables
        self.channel = channel
        self.wave = wave
        self.wavetype = wavetype
        self.amplitude = amplitude
        self.offset = offset
        
        # Get name and period from waveform
        self.name = wave.name() if name is None else name
        if ['.', '_', ':', '-', '*', '+'] in list(self.name):
            raise ValueError ('Name must not contain (._:-)')
        try:
            if period:
               self.period = period
            elif wave.count == float ('inf'):
                self.period = wave.period
            else:
                self.period = wave.period * wave.count
                
        except KeyError:
            raise ValueError ('Must specify period, {wave} has no implicit period')

        # Expand waveform based on type
        # If Arbwave just use those values
        if isinstance (wave, wf.WaveformArb):
            self.length = len (wave)
            self.x = np.linspace (0, self.period, self.length, endpoint=False)
            y = wave.data ()
            
        # otherwise expand based on buffer length
        else:
            if wavetype == 'DDS':
                self.length = Signal.DDS_LENGTH
            else:
                self.length = int (self.period * Signal.TARB_MAX_SRATE)
                # TODO : Lower sampling rate to lower limit
                if self.length > Signal.TARB_LENGTH:
                    raise BoundsError (f'{self.name}: Data exceeds TARB max 8M')
            self.x = np.linspace (0, self.period, self.length, endpoint=False)
            y = [wave.data_at (t) for t in self.x]

        # Normalize values
        self.y = y / np.max(np.abs (y))
        
        # Expand normalized signal to limits
        self.data = [int (v * np.max (Signal.MIN_MAX)) for v in self.y]

    # Show some useful information
    def __str__(self) -> str:
        return f'Signal:{self.wavetype}:{self.length}:{self.name}:{self.period}'
    
    # Wavename with period
    def fullname(self) -> str:
        penc = f'{self.period:0.9f}'.replace ('.', '_')
        return f'{self.name}_{penc}'
    
    # Generate upload command
    def upload(self) -> dict:
        cmd = {
            'message' : f'C{self.channel}:WVDT WVNM,{self.fullname()},WAVEDATA,',
            'values'  : self.data,
            'datatype' : 'h',
            'is_big_endian' : False,
            'termination' : '',
            'encoding' : None,
            'header_fmt' : 'empty',
        }
        return cmd

    # Parse and return a new waveform object
    @staticmethod
    def Parse(resp : bytes, name : str, builtin=False) -> Self:
        # Extract period from name
        if not builtin:
            sep = name.find ('_')
            period = float(name[sep+1:].replace('_', '.'))
            name = name[:sep]
        else:
            period = 1e-3
            
        # Extract data
        data = resp[resp.find (b'WAVEDATA,') + len(b'WAVEDATA,'):]
        data = struct.unpack(f'<{int(len(data)/2)}h', data)
        if len(data) > Signal.DDS_LENGTH:
            return Signal (wave=wf.WaveformArb (data=data, name=name, period=period), wavetype='TARB')
        else:
            return Signal (wave=wf.WaveformArb (data=data, name=name, period=period), wavetype='DDS')

    # Return configuration commands
    def config(self) -> list:
        cmds = [f'C{self.channel}:ARWV NAME,{self.fullname()}']
        cmds += [f'C{self.channel}:SRATE MODE,{self.wavetype}']
        if self.wavetype == 'TARB':
            cmds += [f'C{self.channel}:SRATE VALUE,{round(self.length/self.period):g}']
        else:
            cmds += [f'C{self.channel}:BSWV WVDT,ARB,'
                     f'PERI,{self.period:g},AMP,{self.amplitude},OFST,{self.offset}']
        return cmds

    # Plot signal
    def plot (self) -> None:
        plt.plot (self.x, self.y)
        plt.title (self.name)
        plt.xlabel (f'Time(s) [0, {self.period:g}]')
        plt.ylabel ('Value (normalized)')
        plt.show ()
        
class Siggen:

    # Setup local logging
    logger = logging.getLogger ('Siggen')
    handler = logging.StreamHandler ()
    formatter = logging.Formatter('%(name)s:%(levelname)s:%(message)s')
    handler.setFormatter (formatter)

    # Min values
    BURST_MIN_DELAY = 1e-6
    if not logger.handlers:
        logger.addHandler (handler)
    
    def __init__(self,
                 ip:str,
                 log = logging.CRITICAL
                 ) -> None:
        self.rm = pyvisa.ResourceManager ()
        self.instr = self.rm.open_resource (f'TCPIP0::{ip}::INSTR')
        self.logger.setLevel (level=log)

    def write(self, msg) -> None:
        self.logger.debug (f'>> {msg}')
        self.instr.write (msg)

    def query(self, msg) -> str:
        self.logger.debug (f'>> {msg}')
        resp =  self.instr.query (msg).strip()
        self.logger.debug (f'<< {resp}')
        return resp

    def write_binary_values(self, **kwargs) -> None:
        self.logger.debug (f'>> {kwargs["message"]}...')
        self.instr.write_binary_values (**kwargs)

    def read_raw(self):
        return self.instr.read_raw().strip()
    
    def __str__(self) -> str:
        return self.query ('*IDN?')

    def get_values(self, cmd) -> list:
        resp = self.query (cmd)
        return resp[resp.find (' ')+1:].split(',')

    def get_key_value(self, cmd, key) -> str:
        kv = self.get_values (cmd)
        return kv[kv.index(key) + 1]

    def switch(self, cmd, old, new) -> None:
        vals = self.get_values (f'{cmd}?')
        if old in vals:
            self.write (f'{cmd} {new}')
            
    def set_key_value(self, cmd, key, val) -> None:
        cval = self.get_key_value (f'{cmd}?', key)
        if cval != val:
            self.write (f'{cmd} {key},{val}')
            
    def list_signals(self, builtin=False) -> list:
        if builtin:
            resp = self.query ('STL?')[4:]
            resp = resp.split(',')
            waves = [name.strip() for name in resp if name.strip()[0] == 'M']
        else:
            resp = self.query ('STL? USER')[9:]
            waves = resp.split(',')
        return waves
    
    def set_signal(self, obj : Signal) -> None:
        self.write_binary_values (**obj.upload())
        
    def get_signal(self, name:str='default', builtin:bool=False) -> Signal:
        # Get list of signals
        names = self.list_signals (builtin)

        # If not exact match do fuzzy match (ignore signal period)
        if name not in names:
            matches = [n for n in names if n.split('_')[0] == name]
            if len (matches) > 1:
                raise ValueError (f'Multiple matches: {matches}')
            elif not matches:
                raise ValueError (f'Signal {name} not found')
            else:
                name = matches[0]

        # Set to matching name
        if builtin:
            self.write (f'WVDT? BUILDIN,{name}')
        else:
            self.write (f'WVDT? USER,{name}')

        # Generate object and return
        return Signal.Parse (resp=self.read_raw (), name=name, builtin=builtin)

    def config_signal(self, obj:Signal) -> None:
        # Configure signal
        for cmd in obj.config ():
            self.write (cmd)

    def enable(self, channel:int) -> None:
        self.switch (f'C{channel}:OUTP', 'OFF', 'ON')

    def disable(self, channel:int) -> None:
        self.switch (f'C{channel}:OUTP', 'ON', 'OFF')

    def burst_ext_trigger(self, channel:int, enable:bool) -> None:
        if enable:
            self.set_key_value (f'C{channel}:BTWV', 'TRMD', 'RISE')
        else:
            self.set_key_value (f'C{channel}:BTWV', 'TRMD', 'OFF')

    def combine(self, channel:int) -> None:
        if channel == 0:
            self.switch ('C1:CMBN', 'ON', 'OFF')
            self.switch ('C2:CMBN', 'ON', 'OFF')
        else:
            other = '1' if channel == 2 else 2
            self.switch (f'C{channel}:CMBN', 'OFF', 'ON')
            self.switch (f'C{other}:CMBN', 'ON', 'OFF')

    def trigger_both (self, enable:bool) -> None:
        if enable:
            self.set_key_value ('COUP', 'TRDUCH', 'ON')
        else:
            self.set_key_value ('COUP', 'TRDUCH', 'OFF')

    def sync_phase (self) -> None:
        self.sg.write ('EQPHASE')
        
# Generate oneshot using burst on channel
class BurstOneshot:
    def __init__(self,
                 siggen: Siggen,
                 signal: Signal,
                 delay: float=0.0,
                 count: int=1,
                 ) -> None:
        
        # Save variables
        self.sg = siggen
        self.wave = signal
        self.delay = delay
        self.count = count
        if self.wave.wavetype != 'DDS':
            raise ValueError ('Burst only supports DDS waveforms')
        
    # Trigger oneshot
    def trigger(self):
        self.sg.write (f'C{self.wave.channel}:BTWV MTRIG')

    # Enable output
    def output_enable(self, val : bool):
        if val:
            self.sg.enable (self.wave.channel)
        else:
            self.sg.disable (self.wave.channel)

    # Config for oneshot
    def config(self):

        # Upload waveform
        self.sg.set_signal (self.wave)

        # Config waveform
        self.sg.config_signal (self.wave)

        # Calc count
        count = str(self.count)
        
        # Setup burst
        cmds = [
            'STATE,ON',
            f'DLAY,{self.delay:g}',
            f'TIME,{count}',
            'TRSR,MAN',
            'EDGE,RISE',
            'STPS,0',
            'CARR,WVTP,ARB',
            'GATE_NCYC,NCYC',
        ]
        for cmd in cmds:
            self.sg.write (f'C{self.wave.channel}:BTWV {cmd}')

        # Delay to ensure config is complete
        time.sleep (0.1)

if __name__ == '__main__':
    sg = Siggen ('10.0.1.32', log=logging.DEBUG)
    str (sg)
