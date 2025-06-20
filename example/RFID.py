#!/bin/env python3
'''
RFID utility functions.

- Generate modulated waveforms.
- Destructive modulations for wave combine on siggen.
'''
import math
import Waveform as wf
import SDG2000X as sg

'''
===============================================================
These are waveform extensions from the generic waveform library
===============================================================
'''
class Carrier (wf.Sine):
    LF = 125e3
    HF = 13.56e6
    '''
    Wrapper around Sine wave
    '''
    def __init__ (self,
                  freq : float = 125e3,
                  name : str = 'carrier',
                  count : float = float ('inf'),
                  **kwargs
                  ) -> None:
        super().__init__(period=1/freq, count=count, name=name, **kwargs)

                  
class Modulate (wf.WaveformPeriodic):
    '''
    Represent a modulated carrier
    '''
    def __init__ (self,
                  carrier : wf.WaveformBase,
                  bitstream : list,
                  mod_index : float = 0.5,
                  destructive : bool = False,
                  count : int = float ('inf'),
                  name : str = 'mod',
                  **kwargs
                  ) -> None:
        '''
        bitstream : list of [1, 0, ...]
        carrier : Sine wave with correct frequency
        mod_index : Modulation percentage as float
        destructive : Create inverted destructive wave for combining
        '''
        if destructive:
            self._data_at = self.destructive
            self.carrier = carrier * -1
            default = lambda x: float (0)
        else:
            self._data_at = self.nondestructive
            self.carrier = carrier
            default = self.carrier.data_at
        
        self.bitstream = bitstream
        self.mod_index = mod_index
        super().__init__(period = carrier.period * len (bitstream),
                         name = name,
                         count = count,
                         default = default,
                         **kwargs)

    def destructive (self, timestamp : float) -> float:
        index = int (timestamp / self.carrier.period)
        if self.bitstream[index]:
            return self.carrier.data_at (timestamp) * self.mod_index
        else:
            return float (0)
        
    def nondestructive (self, timestamp : float) -> float:
        ''' Return modulated waveform at timestamp '''
        index = int (timestamp / self.carrier.period)
        if self.bitstream[index]:
            return self.carrier.data_at (timestamp) * (1 - self.mod_index)
        else:
            return self.carrier.data_at (timestamp) 


class UARTModulate (Modulate):
    '''
    Modulate UART data onto carrier
    Wrapper around modulate that generates bitstream
    '''
    def __init__ (self,
                  carrier  : wf.WaveformBase,
                  data     : bytes,
                  parity   : str = 'N',
                  stopbits : int = 2,
                  count    : int = 1,
                  delay    : float = 0.0,
                  cpb      : int = 1, # Cycles per bit
                  **kwargs
                  ) -> None:
        '''
        Create a bitstream from UART binary data.
        '''
        bs = [0] * int(delay / carrier.period)
        p = 0
        
        # Loop through each byte to generate uart stream
        for d in data:
            bs += [1] * cpb
            for _ in range (8):
                bs += [0] * cpb if d & 1 else [1] * cpb
                p ^= d & 1
                d >>= 1
            # Add parity
            if parity == 'E':
                bs += [p] * cpb
            elif parity == 'O':
                bs += [p ^ 1] * cpb
            # Add stopbits
            bs += [0] * stopbits * cpb

        # Create modulate object
        super().__init__(carrier=carrier, bitstream=bs, count=count, **kwargs)


class GapModulate(wf.WaveformSeq):
    '''
    Send data by modulating carrier gap.
    '''
    def __init__(self,
                 carrier      : wf.WaveformBase,
                 bitstream    : list,
                 delay        : float = 0.0,
                 name         : str = "gapMod",
                 count        : int = 1,
                 c_zero       : int = 9,
                 c_one        : int = 15,
                 c_idle       : int = 20,
                 c_transition : int = 4
                 ) -> None:

        
        # Adjust periods to carrier
        t_transition = c_transition * carrier.period
        t_zero = c_zero * carrier.period
        t_one = c_one * carrier.period
        t_idle = c_idle * carrier.period
        
        # Setup transitions
        # \__ = 1
        # \_  = 0
        # /-- = Gap
        zero = wf.WaveformSeq ([wf.Ramp (period=t_transition, up=False),
                                wf.WaveformArb (data=[0, 0], period=t_zero-t_transition)])
        one = wf.WaveformSeq ([wf.Ramp (period=t_transition, up=False),
                                     wf.WaveformArb (data=[0, 0], period=t_one-t_transition)])
        idle = wf.WaveformSeq ([wf.Ramp (period=t_transition, up=True),
                                wf.WaveformArb (data=[1, 1], period=t_idle-t_transition)])

        # Add delay to beginning
        seq = [wf.WaveformArb (data=[1, 1],
                               period=carrier.period * math.ceil (delay/carrier.period))]

        # Iterate bitstream
        for b in bitstream:
            if b:
                seq += [one]
            else:
                seq += [zero]
            seq += [idle]
            
        # Instantiate base
        super().__init__(waves = seq, name=name)

'''
===============================================================
These are Siggen extension to configure trigger a particular
waveform on the siggen.
===============================================================
'''
class CarrierModOneshot:
    '''
    Manually trigger a single oneshot on both channels
    simultaneously.
    '''
    def __init__ (self,
                  siggen : sg.Siggen,
                  carrier : sg.Signal,
                  mod_destruct : sg.Signal,
                  delay : float=0,
                  count : int=1,
                  combine : int=0,
                  keep_carrier : bool=False
                  ) -> None:
        '''
        siggen : Signal generator object
        carrier : carrier signal
        mod_destruct : destructive modulation signal
        delay : destructive modulation delay from carrier start
        combine : Combine output onto one channel
        '''
        # Set min delay
        carrier_delay_cnt = math.ceil (siggen.BURST_MIN_DELAY / carrier.period)
        carrier_delay = carrier_delay_cnt * carrier.period

        # Round delay to nearest carrier
        delay_cnt = math.ceil (delay / carrier.period)
        delay = delay_cnt * carrier.period

        # Carrier count must be >= mod period
        if keep_carrier:
            carrier_cnt = float('inf')
        else:
            carrier_cnt = int(math.ceil (((mod_destruct.period * count) + delay)/ carrier.period))

        # Save variables
        self.sg = siggen
        self.combine = combine
        
        # Setup oneshot objects
        self.carrier = sg.BurstOneshot (
            siggen = siggen,
            signal = carrier,
            delay = carrier_delay,
            count = carrier_cnt,
        )
        self.mod = sg.BurstOneshot (
            siggen = siggen,
            signal = mod_destruct,
            delay = carrier_delay + delay,
            count = count,
        )

    def config (self) -> None:

        # Turn off outputs
        self.carrier.output_enable (0)
        self.mod.output_enable (0)

        # Config each oneshot
        self.carrier.config ()
        self.mod.config ()

        # Setup manual trigger to trigger both
        self.sg.trigger_both (True)

        # Turn on combine if required
        if self.combine:
            self.sg.combine (self.combine)
        else:
            self.sg.combine (0)

        # Turn on outputs
        self.carrier.output_enable (True)
        self.mod.output_enable (True)

    def trigger (self) -> None:
        self.mod.trigger ()

import logging
import time
import argparse
import sys

if __name__ == '__main__':

    # Add arguments
    parser = argparse.ArgumentParser ()
    parser.add_argument ('--debug', action='store_true')
    parser.add_argument ('--carrier', type=float)
    parser.add_argument ('--oneshot', action='store_true')
    parser.add_argument ('--single', action='store_true')
    parser.add_argument ('--gap', action='store_true')
    parser.add_argument ('--tarb_sync', action='store_true')
    parser.add_argument ('--example', action='store_true')
    
    # Parse args
    args = parser.parse_args ()
    if args.debug:
        log = logging.DEBUG
    else:
        log = logging.CRITICAL
        
    # Get siggen instance
    #siggen = sg.Siggen ('10.0.1.32', log=log)

    # Generate carrier
    if not args.carrier:
        args.carrier = 125e3
    carrier = Carrier (freq=args.carrier)

    # Generate oneshot synchronized modulation
    if args.oneshot:
        # Modulate with destructive waveform
        mod = UARTModulate (
            carrier,
            b'uart',
            destructive=True
        )    

        # Create signals
        s_carrier = sg.Signal (
            carrier,
            amplitude=10,
            channel=1,
            wavetype='DDS'
        )
        s_mod = sg.Signal (
            mod,
            amplitude=3,
            channel=2,
            wavetype='DDS'
        )
        
        # Generate oneshot burst
        burst = CarrierModOneshot (
            siggen = siggen,
            carrier = s_carrier,
            mod_destruct = s_mod,
            combine = 1,
            #delay = 1e-3,
            keep_carrier = False
        )
        burst.config ()
        siggen.burst_ext_trigger (2, True)
        burst.trigger ()

    # Generate oneshot on single channel
    # Modulation already applied to carrier
    elif args.single:
        
        # Modulate with destructive waveform
        mod = UARTModulate (
            carrier,
            b'test',
            mod_index = 0.2,
            destructive = False,
            #delay = 500e-6
        )    
        
        # Create signals
        s_mod = sg.Signal (mod, amplitude=10, channel=2, wavetype = 'DDS')

        # Instantiate oneshot
        burst = sg.BurstOneshot (
            siggen = siggen,
            signal = s_mod,
            delay = 0,
            count = 1,
        )

        # Disable output
        siggen.disable (s_mod.channel)

        # Setup burst
        burst.config ()
        #siggen.burst_ext_trigger (s_mod.channel, True)

        # Enable channel
        siggen.enable (s_mod.channel)

        # Trigger
        burst.trigger ()

    # Generate gap modulation
    elif args.gap:

        env = GapModulate (carrier, [1,0])

        # Create signals
        s_mod = sg.Signal (env * carrier, amplitude=10, channel=2, name='gapMod', wavetype='TARB')
        s_env = sg.Signal (env, amplitude=10, channel=1, name='env', wavetype='TARB')

        # Upload signals
        siggen.set_signal (s_mod)
        siggen.set_signal (s_env)

        # Config signals
        siggen.config_signal (s_mod)
        siggen.config_signal (s_env)

    # Synchronous TARB on both channels
    elif args.tarb_sync:
        # Modulate with destructive waveform
        mod = UARTModulate (
            carrier,
            b'uart',
            destructive=True
        )    

        carrier = Carrier (freq=args.carrier)

        # Create signals
        s_carrier = sg.Signal (
            carrier,
            amplitude=10,
            channel=1,
            wavetype='TARB'
        )
        s_mod = sg.Signal (
            mod,
            amplitude=3,
            channel=2,
            wavetype='TARB'
        )

        # Upload signals
        siggen.set_signal (s_mod)
        siggen.set_signal (s_carrier)

        # Config signals
        siggen.config_signal (s_mod)
        siggen.config_signal (s_carrier)

    # Example for SIGLENT support
    elif args.example:

        # Destructive mod
        mod = UARTModulate (
            carrier,
            b'test',
            mod_index = 0.2,
            destructive = True,
            delay = 100e-6,
            name = 'Mod (C2)'
        )    

        combine = wf.WaveformAdd ([carrier, mod], name='C1+C2')
        plot = wf.WaveformPlot ([carrier, mod, combine])
        plot.plot ()
