### Install
git clone https://github.com/tinylabs/SDG2000X.git
cd SDG2000X
pip install -u .

### Example
~~~
from SDG2000X import Siggen, Signal
import Waveform as wf

# Approximate square wave with combination of sine wave odd harmonics
harmonics = [wf.Sine (1e-3/x,
                   count=float('inf'),
                   name=f'sine({1e-3/x:g})'
                   ) * (1/x) for x in range (1, 40, 2)]
# Add harmonics pointwise
square = wf.WaveformAdd (harmonics, name='sin_odd')

# Generate quantized signal to upload
sig = Signal (square, amplitude=10, channel=1)

# Connect to siggen and configure
sdg = Siggen ('10.0.1.32')
sdg.set_signal (sig)
sdg.config_signal (sig)

# Plot signal that should now  be on channel 1
# Also plot all the harmonics that were added
plot = wf.WaveformPlot ([square] + harmonics)
plot.plot ('Sine odd harmonics', legend = False)
~~~

More examples (RFID related) in examples/ directory.
