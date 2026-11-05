"""USB-config. Draait een keer bij elke reset.

De host ziet straks alleen:
  - een HID-muis
  - een HID-toetsenbord (alleen voor de sprong uit de bus)
  - een CDC data-kanaal (commando's)
  - het CIRCUITPY-station (dev convenience)

Beide HID-interfaces zijn generiek: geen vendor-ID, geen naam die naar een
tool verwijst. Van buiten is dit een muis en een toetsenbord.
"""

import usb_hid
import usb_cdc

usb_hid.enable((usb_hid.Device.MOUSE, usb_hid.Device.KEYBOARD))

# console=True houdt de REPL bruikbaar voor debuggen,
# data=True is het kanaal dat de PC gebruikt.
usb_cdc.enable(console=True, data=True)
