"""Ingest: steps 2-3 of the scan pipeline.

2 Receive: Start Receiving runs a small server on the local network (random token, photos only)
  and shows a QR code; the iPhone opens it in Safari and uploads photos into zz.Originals. The
  eye button watches zz.Source_Photos instead (USB / Drive drops).
3 Convert & Sort (also starts by itself once uploads stop): keeps the JPGs, converts HEIC / RAW
  that have no JPG (pillow-heif / rawpy, EXIF kept), moves originals, iPhone edits, videos and
  duplicate Drive copies into zz.Originals. "Install converters" fetches the packages once.
"""
from . import operators


def register():
    operators.register()


def unregister():
    operators.unregister()
