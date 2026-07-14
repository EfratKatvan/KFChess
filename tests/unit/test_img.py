import numpy as np

from kungfu_chess.view.img import Img


def make_img(pixels: np.ndarray) -> Img:
    img = Img()
    img.img = pixels
    return img


def test_strip_background_makes_uniform_corners_transparent():
    canvas = np.full((4, 4, 3), 255, dtype=np.uint8)  # solid white background
    canvas[1:3, 1:3] = (0, 0, 0)  # black foreground square in the middle
    img = make_img(canvas)

    img.strip_background()

    assert img.img.shape == (4, 4, 4)
    assert img.img[0, 0, 3] == 0  # corner (background) is transparent
    assert img.img[2, 2, 3] == 255  # center (foreground) is opaque


def test_strip_background_is_a_no_op_for_images_that_already_have_alpha():
    canvas = np.zeros((2, 2, 4), dtype=np.uint8)
    canvas[..., 3] = 128
    img = make_img(canvas)

    img.strip_background()

    assert img.img.shape == (2, 2, 4)
    assert (img.img[..., 3] == 128).all()
