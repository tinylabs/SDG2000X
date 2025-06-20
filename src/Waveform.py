#!/bin/env python3
#
# Generate waveform modulated data for siggen
#
# All rights reserved
# Tiny Labs Inc
# 2025
#
import math
import numpy as np
from typing import Literal, Self
from abc import abstractmethod
import matplotlib.pyplot as plt

class WaveformBase:
    '''
    Base class for waveforms. 
    Modifier classes should inherit this class.
    Waveform classes with data should inherit Waveform.
    '''
    def __init__(self,
                 name : str = None,
                 data : float = 0.0,
                 **kwargs
                 ) -> None:
        '''
        name (optional) : Name of waveform
        '''
        # Store any other class variables
        self.__dict__.update (kwargs)
        self.__name = 'default' if name is None else name
        self.__data = data
        
    @abstractmethod
    def data_at (self, timestamp : float) -> float:
        '''
        Get data at point
        Override in derived classes.
        '''
        return self.__data

    def name (self) -> str:
        return self.__name

    def get_period (self) -> float:
        '''
        Best effort to get period.
        Used by modifiers to propagate period over operations.
        '''
        if 'period' in self.__dict__.keys():
            return self.period
        else:
            return 0
        
    '''
    Dunder methods to handle transforms on waveform
    '''
    def __add__ (self, other) -> Self:
        if isinstance (other, WaveformBase):
            name = f'({self.name()}+{other.name()})'
        else:
            name = f'({self.name()}+{other:g})'
        return WaveformAdd ([self, other], name=name, **self.__dict__.copy())

    def __iadd__ (self, other) -> Self:
        return self.__add__ (other)

    def __mul__ (self, other) -> Self:
        if isinstance (other, WaveformBase):
            name = f'({self.name()}*{other.name()})'
        else:
            name = f'({self.name()}*{other:g})'
        return WaveformMultiply ([self, other], name=name, **self.__dict__.copy())
        
    def __imul__ (self, other) -> Self:
        return self.__mul__ (other)

    def __str__ (self) -> str:
        return f'{self.__class__.__name__}:{self.name()}'
    
class WaveformAdd (WaveformBase):
    '''
    Add waveforms pointwise
    '''
    def __init__ (self,
                  waves : list,
                  **kwargs
                  ) -> None:
        
        # Convert int/floats into base waveforms
        self.__waves = [w if isinstance (w, WaveformBase) else WaveformBase (data=float(w)) for w in waves]
        self.period = np.max (list (map (lambda w: w.get_period(), self.__waves)))
        self.count = 1
        super().__init__ (**kwargs)

    def data_at (self, timestamp : float) -> float:
        ''' Pointwise addition of all waveforms '''
        data = list (map (lambda w: w.data_at (timestamp), self.__waves))
        return np.sum (data)
    
class WaveformMultiply (WaveformBase):
    '''
    Multiply waveforms pointwise.
    '''
    def __init__ (self,
                  waves : list,
                  **kwargs
                  ) -> None:

        # Convert int/floats into base waveforms
        self.__waves = [w if isinstance (w, WaveformBase) else WaveformBase (data=float(w)) for w in waves]
        self.period = np.max (list (map (lambda w: w.get_period(), self.__waves)))
        self.count = 1
        super().__init__ (**kwargs)

    def data_at (self, timestamp : float) -> float:
        ''' Pointwise addition of all waveforms '''
        data = list (map (lambda w: w.data_at (timestamp), self.__waves))
        return np.prod (data)


# TODO: Create filter class to apply filter data points
# will only work once waveform has been expanded by resolution
class WaveformFilter:
    def __init__ (self):
        pass
    
class WaveformPeriodic (WaveformBase):
    '''
    Waveform class to describe waveforms with data.
    '''    
    def __init__(self,
                 period : float,
                 count : int = 1,
                 default = lambda x: 0,
                 **kwargs
                 ) -> None:
        '''
        Required:
        period: period of waveform in seconds

        Optional:
        count : Repeat count for full waveform or float('inf')
        '''

        # Save variables
        self.period = float(period)
        self.count = count
        self.__default = default
        
        # Instantiate
        super().__init__ (**kwargs)

    def __str__ (self) -> str:
        return super().__str__() + f':{self.period:g}:{self.count}'

    def data_at (self, timestamp : float) -> float:
        ''' 
        Get data at point.
        '''
        #Handle aliasing over period.
        if timestamp >= self.period * self.count:
            return self.__default (timestamp)
        else:
            return self._data_at (timestamp % self.period)

class Delay (WaveformPeriodic):
    '''
    Generate a delay with empty data.
    '''
    def __init__(self,
                 period : float,
                 val : float = 0.0,
                 count : float = 1
                 ) -> None:
        self.__val = float (val)
        super().__init__(period=period, count=count, name='')

    def _data_at (self, timestamp : float) -> float:
        return self.__val
        
class WaveformArb (WaveformPeriodic):
    '''
    Represents arbitrary waveform with data points
    '''
    def __init__ (self,
                  period : float,
                  data : list,
                  count : int = 1,
                  **kwargs
                  ) -> None:
        # Save data
        self.__data = data

        # Instantiate
        super().__init__ (period=period, count=count, **kwargs)

    # Timestep per sample
    def __timestep (self) -> float:
        return self.period / (len (self.__data) - 1)

    # Get previous timestamp in dataset
    def __timestamp (self, timestamp) -> float:
        timestamp = int(timestamp/self.__timestep()) * self.__timestep()
        return timestamp if timestamp < self.period else self.period

    # Get data index at timestamp
    def __index (self, timestamp) -> int:
        idx = int (timestamp / self.__timestep ())
        return idx if idx < len (self.__data) - 1 else len (self.__data) - 1
    
    # Get index, data before or equal to timestamp
    def __before (self, timestamp : float) -> tuple:
        return (self.__timestamp (timestamp),
                self.__data[self.__index (timestamp)]) 

    # Get index,data after timestamp
    def __after (self, timestamp : float) -> tuple:
        return (self.__timestamp (timestamp) + self.__timestep (),
                self.__data[self.__index (timestamp + self.__timestep ())]) 

    def _data_at (self, timestamp : float) -> float:
        x1, y1 = self.__before (timestamp)
        x2, y2 = self.__after (timestamp)
        return y1 + (timestamp - x1) * (y2 - y1) / (x2 - x1)

    def __len__ (self) -> int:
        return len (self.__data)

    def data (self) -> list:
        return self.__data
    
class WaveformSeq (WaveformPeriodic):
    '''
    Combine list of waveforms into a sequence
    '''
    def __init__ (self,
                  waves : list = None,
                  **kwargs
                  ) -> None:

        # Generate
        if waves:
            # Save variables
            self.__waves = waves if isinstance (waves, list) else [waves]
            period = np.sum (list(map(lambda w : w.period, self.__waves)))
        else:
            # Create empty object
            self.__waves = list()
            period = 0
            
        # Instantiate
        super().__init__(period=period, **kwargs)

    def _data_at (self, timestamp : float) -> float:
        ''' Get data at time '''
        ctime = 0
        for wave in self.__waves:
            if timestamp < ctime + wave.period * wave.count:
                return wave.data_at (timestamp - ctime)
            ctime += wave.period * wave.count

        # Past end of waveforms
        return 0

    def __index__ (self, idx) -> Self:
        return self.__waves[idx]

    def append (self, wave) -> None:
        self.__waves += [wave]
        self.period += wave.period

    def prepend (self, wave) -> None:
        self.__waves = [wave] + self.__waves
        self.period += wave.period
        
class Sine (WaveformPeriodic):
    '''
    Represent a sine wave.
    '''
    def __init__(self,
                 period : float,
                 **kwargs
                 ) -> None:

        # Instantiate Waveform
        super().__init__ (period, **kwargs)
        
    def _data_at (self, timestamp : float) -> float:
        return np.sin (timestamp/self.period * 2 * np.pi)
        
class Square (WaveformPeriodic):
    '''
    Represent a square wave.
    '''
    def __init__(self,
                 period : float,
                 duty : float = 0.5,
                 count : float = float ('inf'),
                 **kwargs
                 ) -> None:

        # Check bounds on duty cycle
        if duty >= 1.0 or duty <= 0:
            raise ValueError (f'{self.__class__.__name__}: Duty must be (0.0, 1.0)')
        
        # Save duty cycle
        self.duty = duty
        
        # Instantiate Waveform
        super().__init__ (period, count=count, **kwargs)
        
    def _data_at (self, timestamp : float) -> float:
        return float(1) if timestamp < self.period * self.duty else float(-1)

    def __str__ (self):
        return super().__str__() + f':duty={self.duty:g}'

class Ramp (WaveformArb):
    '''
    Represents ramp waveform as arb wave with 2 points
    '''
    def __init__(self,
                 period : float,
                 count : float = 1,
                 up : bool = True,
                 **kwargs
                 ) -> None:

        # Instantiate
        if up:
            super().__init__ (data=[0, 1], period=period, count=count, **kwargs)
        else:
            super().__init__ (data=[1, 0], period=period, count=count, **kwargs)

class WaveformPlot:
    '''
    Plot one or more waveforms using pyplot
    '''
    def __init__ (self,
                  waves : list,
                  timescale : list = None,
                  resolution : int = 1e5
                  ) -> None:
        '''
        waves : Singular Waveform or list of waveforms
        timescale: 
          list : [start, end] of plotting timescale.
          float : end of timescale, implicit start @ 0.
          None : Plot entires waveform.
        resolution:
          int : Points per period
        '''
        # Convert singular to list
        self.waves = [waves] if isinstance (waves, WaveformBase) else waves

        # Store timescale
        if timescale is None:
            max_time = np.max (list (map (lambda w: w.period * w.count, self.waves)))
            max_period = np.max (list (map (lambda w: w.period, self.waves)))
            self.timescale = [0, max_time] if max_time != float ('inf') else [0, max_period]
        elif isinstance (timescale, float):
            self.timescale = [0, timescale]
        else:
            self.timescale = timescale
        self.resolution = int(resolution)
        
    def plot (self,
              title : str = 'WaveformPlot',
              legend : bool = True,
              block : bool = True,
              **kwargs
              ):
        '''
        Plot list of waveforms.
        '''
        # Set x-axis
        x = np.linspace (self.timescale[0], self.timescale[1],
                         self.resolution, endpoint=False)

        # Get plots
        fig, ax = plt.subplots ()

        # Plot all waveforms
        for wave in self.waves:

            y = [wave.data_at (_) for _ in x]
            ax.plot (x, y, label=str(wave))

        # Show plots
        plt.title (title)
        if legend:
            plt.legend ()
        plt.show (block=block)

    def plotFFT (self, **kwargs):
        pass
        
if __name__ == '__main__':

    # Approximate square wave with combination of sine wave odd harmonics
    harmonics = [
        Sine (1e-3/x,
              count=float('inf'),
              name=f'sine({1e-3/x:g})'
              ) * (1/x) for x in range (1, 40, 2)]
    square = WaveformAdd (harmonics, name='sin_odd')
    plot = WaveformPlot ([square] + harmonics)
    plot.plot ('Sine odd harmonics', legend = False)
    
