"""The pixel audit every capture harness runs on a frame it just grabbed.

A capture that only checks that its PNGs exist publishes blank pages: the
files are there, and they are empty. So each harness reads the pixels back
and measures what only holds when the UI really drew. The arithmetic is here
once; the thresholds stay with each harness, because each one is calibrated
against that toolkit's measured output.

`stats()` returns the four numbers `parity_report.write_report` publishes per
page:

  colours  distinct RGB values among the samples
  flat     share of the samples that are the single most common colour
  ink      share of the samples that `ink(luma)` accepts
  stddev   grayscale standard deviation, 0..1: the "is the screen blank"
           measure the VM walkthrough takes with ImageMagick. Reported only;
           no harness gates on it.

Luma is the integer `(30 R + 59 G + 11 B) // 100`. The default `ink` rule is
for a light theme (dark pixels are ink) and the default `step` samples every
third pixel of every third row. A dark theme passes its own rule, for example
`ink=lambda luma: luma > 60`.
"""


def dark(luma):
    """The ink rule for a light theme: text and icons are the dark pixels."""
    return luma < 160


def stats(width, height, pixel, step=3, ink=dark):
    """Audit a `width` x `height` image. `pixel(x, y)` returns `(r, g, b)`.

    Returns None for an image with no pixels.
    """
    counts, samples, inked = {}, 0, 0
    luma_sum = luma_sq = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            px = pixel(x, y)
            counts[px] = counts.get(px, 0) + 1
            samples += 1
            luma = (30 * px[0] + 59 * px[1] + 11 * px[2]) // 100
            luma_sum += luma
            luma_sq += luma * luma
            if ink(luma):
                inked += 1
    if not samples:
        return None
    mean = luma_sum / samples
    var = max(luma_sq / samples - mean * mean, 0.0)
    return {"colours": len(counts),
            "flat": max(counts.values()) / samples,
            "ink": inked / samples,
            "stddev": (var ** 0.5) / 255.0}


def pixbuf_stats(pixbuf, **kwargs):
    """`stats()` for a GdkPixbuf (GTK 3 and GTK 4 harnesses)."""
    data = pixbuf.get_pixels()
    stride, chans = pixbuf.get_rowstride(), pixbuf.get_n_channels()

    def pixel(x, y):
        i = y * stride + x * chans
        return (data[i], data[i + 1], data[i + 2])

    return stats(pixbuf.get_width(), pixbuf.get_height(), pixel, **kwargs)


def qimage_stats(image, **kwargs):
    """`stats()` for a QImage (Qt Quick harnesses)."""
    def pixel(x, y):
        c = image.pixel(x, y)
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)

    return stats(image.width(), image.height(), pixel, **kwargs)


def png_stats(path, **kwargs):
    """`stats()` for a PNG file, through Pillow or, without it, GdkPixbuf.

    Raises when neither library can be imported.
    """
    try:
        from PIL import Image
    except ImportError:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        return pixbuf_stats(GdkPixbuf.Pixbuf.new_from_file(path), **kwargs)
    with Image.open(path) as im:
        im = im.convert("RGB")
        px = im.load()
        return stats(im.size[0], im.size[1], lambda x, y: px[x, y], **kwargs)
