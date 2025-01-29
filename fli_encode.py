import struct
import io
from enum import IntEnum
from contextlib import contextmanager
import itertools
from dataclasses import dataclass


def rle_encode(data: bytes, dest: io.BufferedIOBase) -> int:
    packet_count = 0

    if not data:
        return packet_count

    last_n = 0
    different = True
    for n, byte in enumerate(data[1:], 1):
        previous_byte = data[n - 1]
        if byte == previous_byte:
            if different:
                if last_n < n - 1:
                    # write previous "literal run", until n - 2
                    count = n - 1 - last_n
                    dest.write(struct.pack("<b", -count))
                    dest.write(data[last_n:n - 1])
                    packet_count += 1
                last_n = n - 1
                different = False
        elif not different:
            count = n - last_n
            dest.write(struct.pack("<bB", count, previous_byte))
            packet_count += 1
            last_n = n
            different = True

    count = len(data) - last_n
    if different:
        dest.write(struct.pack("<b", -count))
        dest.write(data[last_n:])
        packet_count += 1
    else:
        dest.write(struct.pack("<bB", count, data[-1]))
        packet_count += 1

    return packet_count


class FliChunkType(IntEnum):
    COLOR_256 = 4
    BYTE_RUN = 15
    FLI_COPY = 16
    FRAME_TYPE = 0xF1FA


def write_byte_run(data: bytes, line_length: int, dest: io.BufferedIOBase):
    with io.BytesIO() as chunk:
        if len(data) % line_length:
            raise ValueError()

        for offset in range(0, len(data), line_length):
            line = data[offset:offset + line_length]
            with io.BytesIO() as line_data:
                packet_count = rle_encode(line, line_data)
                if packet_count > 0xff:
                    packet_count = 0
                chunk.write(struct.pack("<b", packet_count))
                chunk.write(line_data.getvalue())

        write_chunk_data(FliChunkType.BYTE_RUN, chunk.getbuffer(), dest)


class SubchunkType():
    def __init__(self):
        self._subchunks = []

    @property
    def count(self):
        return len(self._subchunks)

    @property
    def subchunks(self) -> list[bytes]:
        return self._subchunks

    @contextmanager
    def write_subchunk(self):
        with io.BytesIO() as subchunk:
            yield subchunk

            buffer = subchunk.getvalue()
            if buffer:
                self._subchunks.append(buffer)


def write_frame_type(subchunks: list[bytes], dest: io.BufferedIOBase, *, delay: int = 0, width: int = 0, height: int = 0):
    with io.BytesIO() as chunk:
        chunk.write(struct.pack("<HHHHH", len(subchunks), delay, 0, width, height))
        for subchunk in subchunks:
            chunk.write(subchunk)

        write_chunk_data(FliChunkType.FRAME_TYPE, chunk.getvalue(), dest)


def write_chunk_data(type: FliChunkType, data: bytes, dest: io.BufferedIOBase):
    dest.write(struct.pack("<IH", len(data) + 6, type))
    dest.write(data)


@dataclass
class Color:
    r: int
    g: int
    b: int

    def __bytes__(self) -> bytes:
        return struct.pack("<BBB", self.r, self.g, self.b)


def write_palette_packet(colors: list[Color], skip: int, dest: io.BufferedIOBase):
    if len(colors) > 256:
        raise ValueError("Too many colors assigned")
    dest.write(struct.pack("<BB", skip, len(colors) % 256))
    for color in colors:
        dest.write(bytes(color))


def write_palette(colors: list[Color], dest: io.BufferedIOBase):
    with io.BytesIO() as chunk:
        chunk.write(struct.pack("<H", 1))
        colors = list(colors)
        colors.extend([Color(0, 0, 0)] * (256 - len(colors)))
        write_palette_packet(colors, 0, chunk)

        write_chunk_data(FliChunkType.COLOR_256, chunk.getvalue(), dest)


def write_header(frames: list[bytes], width: int, height: int, delay: int, dest: io.BufferedIOBase):
    created = 0
    creator = 0
    updated = 0
    updater = 0
    dest.write(
        struct.pack(
            "<IHHHHHHI2xIIIIHH2x2x2x4x2x2x24x4x4x40x",
            sum(len(frame) for frame in frames) + 128,
            0xAF12,
            len(frames),
            width,
            height,
            8,
            0,
            delay,
            created,
            creator,
            updated,
            updater,
            1,
            1))

    for frame in frames:
        dest.write(frame)


class FlicFile:

    def __init__(self, width: int, height: int, delay: int):
        self._palette = []
        self._frames = []
        self._next_palette = None
        self._width = width
        self._height = height
        self._delay = delay

    def set_palette(self, colors: list[Color]):
        self._next_palette = colors

    def add_frame(self, image: bytes):
        with io.BytesIO() as frame:
            if image is None:
                write_frame_type([], frame)
            else:
                subchunks = SubchunkType()
                if not self._palette or self._next_palette:
                    if not self._next_palette:
                        raise ValueError("Palette not set")

                    self._palette = self._next_palette
                    self._next_palette = None
                    with subchunks.write_subchunk() as subchunk:
                        write_palette(self._palette, subchunk)
                with subchunks.write_subchunk() as subchunk:
                    write_byte_run(image, self._width, subchunk)
                write_frame_type(subchunks.subchunks, frame)
            self._frames.append(frame.getvalue())

    def write(self, dest: io.BufferedIOBase):
        write_header(self._frames, self._width, self._height, self._delay, dest)