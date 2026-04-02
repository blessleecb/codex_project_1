from __future__ import annotations

import html
import re
import struct
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET
from zipfile import ZipFile


def column_letters_to_index(value: str) -> int:
    result = 0
    for char in value:
        if not char.isalpha():
            break
        result = result * 26 + (ord(char.upper()) - 64)
    return result - 1


def excel_serial_to_iso(value: float) -> str:
    # Excel's day 1 is 1899-12-31 with the 1900 leap year bug.
    from datetime import datetime, timedelta

    epoch = datetime(1899, 12, 30)
    converted = epoch + timedelta(days=float(value))
    if converted.time().hour or converted.time().minute or converted.time().second:
        return converted.strftime("%Y-%m-%d %H:%M:%S")
    return converted.strftime("%Y-%m-%d")


def read_xlsx(path: Path) -> Dict[str, List[List[str]]]:
    with ZipFile(path) as archive:
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for item in root.findall("a:si", namespace):
                texts = [node.text or "" for node in item.findall(".//a:t", namespace)]
                shared_strings.append("".join(texts))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rel_namespace = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in relationships
            if rel.tag.endswith("Relationship")
        }

        sheets: Dict[str, List[List[str]]] = {}
        for sheet in workbook.findall("a:sheets/a:sheet", namespace):
            name = sheet.attrib["name"]
            rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = rel_map[rel_id]
            sheet_root = ET.fromstring(archive.read(f"xl/{target}"))
            rows: List[List[str]] = []
            for row in sheet_root.findall(".//a:sheetData/a:row", namespace):
                values: Dict[int, str] = {}
                for cell in row.findall("a:c", namespace):
                    reference = cell.attrib.get("r", "")
                    col_index = column_letters_to_index(re.sub(r"\d", "", reference))
                    cell_type = cell.attrib.get("t")
                    value_node = cell.find("a:v", namespace)
                    inline_node = cell.find("a:is", namespace)
                    value = ""
                    if cell_type == "s" and value_node is not None:
                        value = shared_strings[int(value_node.text or "0")]
                    elif cell_type == "inlineStr" and inline_node is not None:
                        value = "".join(node.text or "" for node in inline_node.findall(".//a:t", namespace))
                    elif value_node is not None and value_node.text is not None:
                        raw = value_node.text
                        if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
                            value = raw
                        else:
                            value = raw
                    values[col_index] = value
                if values:
                    width = max(values) + 1
                    rows.append([values.get(index, "") for index in range(width)])
            sheets[name] = rows
        return sheets


class _HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._current_table: List[List[str]] = []
        self._current_row: List[str] = []
        self._current_cell: List[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "table":
            self._current_table = []
        elif tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._current_row.append(html.unescape("".join(self._current_cell)).replace("\xa0", " ").strip())
            self._in_cell = False
        elif tag == "tr" and self._current_row:
            self._current_table.append(self._current_row)
        elif tag == "table" and self._current_table:
            self.tables.append(self._current_table)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def read_html_xls(path: Path) -> List[List[List[str]]]:
    parser = _HTMLTableParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.tables


@dataclass
class _OleHeader:
    sector_shift: int
    mini_sector_shift: int
    num_fat_sectors: int
    first_dir_sector: int
    mini_stream_cutoff: int
    first_mini_fat_sector: int
    num_mini_fat_sectors: int
    first_difat_sector: int
    num_difat_sectors: int
    difat: List[int]


class XlsReader:
    FREESECT = 0xFFFFFFFF
    ENDOFCHAIN = 0xFFFFFFFE

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()
        self.header = self._parse_header()
        self.sector_size = 1 << self.header.sector_shift
        self.mini_sector_size = 1 << self.header.mini_sector_shift
        self.fat = self._build_fat()
        self.directories = self._read_directories()
        self.root_entry = next(entry for entry in self.directories if entry["name"] == "Root Entry")
        self.mini_stream = self._read_stream(self.root_entry)
        self.mini_fat = self._build_mini_fat()

    def _parse_header(self) -> _OleHeader:
        header = self.data[:512]
        if header[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError("Not a valid OLE compound file")
        difat = list(struct.unpack("<109L", header[76:76 + 109 * 4]))
        return _OleHeader(
            sector_shift=struct.unpack("<H", header[30:32])[0],
            mini_sector_shift=struct.unpack("<H", header[32:34])[0],
            num_fat_sectors=struct.unpack("<L", header[44:48])[0],
            first_dir_sector=struct.unpack("<L", header[48:52])[0],
            mini_stream_cutoff=struct.unpack("<L", header[56:60])[0],
            first_mini_fat_sector=struct.unpack("<L", header[60:64])[0],
            num_mini_fat_sectors=struct.unpack("<L", header[64:68])[0],
            first_difat_sector=struct.unpack("<L", header[68:72])[0],
            num_difat_sectors=struct.unpack("<L", header[72:76])[0],
            difat=difat,
        )

    def _sector_offset(self, sector_id: int) -> int:
        return (sector_id + 1) * self.sector_size

    def _read_sector(self, sector_id: int) -> bytes:
        offset = self._sector_offset(sector_id)
        return self.data[offset: offset + self.sector_size]

    def _build_fat(self) -> List[int]:
        difat = [value for value in self.header.difat if value not in (self.FREESECT,)]
        next_sector = self.header.first_difat_sector
        for _ in range(self.header.num_difat_sectors):
            if next_sector in (self.ENDOFCHAIN, self.FREESECT):
                break
            sector = self._read_sector(next_sector)
            entries = list(struct.unpack("<127L", sector[:127 * 4]))
            difat.extend([value for value in entries if value != self.FREESECT])
            next_sector = struct.unpack("<L", sector[127 * 4:128 * 4])[0]
        fat: List[int] = []
        for sector_id in difat[: self.header.num_fat_sectors]:
            fat.extend(struct.unpack(f"<{self.sector_size // 4}L", self._read_sector(sector_id)))
        return fat

    def _read_chain(self, start_sector: int, fat: List[int]) -> bytes:
        if start_sector in (self.ENDOFCHAIN, self.FREESECT):
            return b""
        chunks: List[bytes] = []
        sector = start_sector
        seen = set()
        while sector not in (self.ENDOFCHAIN, self.FREESECT):
            if sector in seen:
                break
            seen.add(sector)
            chunks.append(self._read_sector(sector))
            sector = fat[sector]
        return b"".join(chunks)

    def _read_directories(self) -> List[Dict[str, object]]:
        raw = self._read_chain(self.header.first_dir_sector, self.fat)
        directories: List[Dict[str, object]] = []
        for offset in range(0, len(raw), 128):
            entry = raw[offset: offset + 128]
            if not entry.strip(b"\x00"):
                continue
            name_length = struct.unpack("<H", entry[64:66])[0]
            name = entry[: max(0, name_length - 2)].decode("utf-16le", errors="ignore")
            directories.append(
                {
                    "name": name,
                    "type": entry[66],
                    "start_sector": struct.unpack("<L", entry[116:120])[0],
                    "size": struct.unpack("<Q", entry[120:128])[0],
                }
            )
        return directories

    def _build_mini_fat(self) -> List[int]:
        raw = self._read_chain(self.header.first_mini_fat_sector, self.fat)
        if not raw:
            return []
        return list(struct.unpack(f"<{len(raw) // 4}L", raw))

    def _read_mini_stream(self, start_sector: int, size: int) -> bytes:
        chunks: List[bytes] = []
        sector = start_sector
        seen = set()
        while sector not in (self.ENDOFCHAIN, self.FREESECT):
            if sector in seen:
                break
            seen.add(sector)
            offset = sector * self.mini_sector_size
            chunks.append(self.mini_stream[offset: offset + self.mini_sector_size])
            sector = self.mini_fat[sector]
        return b"".join(chunks)[:size]

    def _read_stream(self, entry: Dict[str, object]) -> bytes:
        start_sector = int(entry["start_sector"])
        size = int(entry["size"])
        if size < self.header.mini_stream_cutoff and entry["name"] != "Root Entry":
            return self._read_mini_stream(start_sector, size)
        return self._read_chain(start_sector, self.fat)[:size]

    def workbook_stream(self) -> bytes:
        for candidate in ("Workbook", "Book"):
            for entry in self.directories:
                if entry["name"] == candidate:
                    return self._read_stream(entry)
        raise ValueError("Workbook stream not found")


def _decode_short_unicode(data: bytes, offset: int) -> Tuple[str, int]:
    if offset >= len(data):
        return "", offset
    char_count = data[offset]
    offset += 1
    options = data[offset]
    offset += 1
    is_16bit = options & 0x01
    has_rich = options & 0x08
    has_ext = options & 0x04
    rich_runs = struct.unpack("<H", data[offset: offset + 2])[0] if has_rich else 0
    if has_rich:
        offset += 2
    ext_size = struct.unpack("<L", data[offset: offset + 4])[0] if has_ext else 0
    if has_ext:
        offset += 4
    text_length = char_count * (2 if is_16bit else 1)
    raw = data[offset: offset + text_length]
    text = raw.decode("utf-16le" if is_16bit else "latin1", errors="ignore")
    offset += text_length + rich_runs * 4 + ext_size
    return text, offset


def _decode_long_unicode(data: bytes, offset: int) -> Tuple[str, int]:
    char_count = struct.unpack("<H", data[offset: offset + 2])[0]
    offset += 2
    options = data[offset]
    offset += 1
    is_16bit = options & 0x01
    has_rich = options & 0x08
    has_ext = options & 0x04
    rich_runs = struct.unpack("<H", data[offset: offset + 2])[0] if has_rich else 0
    if has_rich:
        offset += 2
    ext_size = struct.unpack("<L", data[offset: offset + 4])[0] if has_ext else 0
    if has_ext:
        offset += 4
    text_length = char_count * (2 if is_16bit else 1)
    raw = data[offset: offset + text_length]
    text = raw.decode("utf-16le" if is_16bit else "latin1", errors="ignore")
    offset += text_length + rich_runs * 4 + ext_size
    return text, offset


def _parse_sst(data: bytes) -> List[str]:
    offset = 8
    strings: List[str] = []
    while offset < len(data):
        text, next_offset = _decode_long_unicode(data, offset)
        strings.append(text)
        offset = next_offset
    return strings


def _rk_to_float(value: int) -> float:
    is_integer = value & 0x02
    divide_by_100 = value & 0x01
    if is_integer:
        result = value >> 2
    else:
        packed = struct.pack("<Q", (value & 0xFFFFFFFC) << 32)
        result = struct.unpack("<d", packed)[0]
    if divide_by_100:
        result /= 100
    return float(result)


def read_xls(path: Path) -> Dict[str, List[List[str]]]:
    reader = XlsReader(path)
    workbook = reader.workbook_stream()
    sst: List[str] = []
    sheet_offsets: List[Tuple[str, int]] = []
    formats: Dict[int, str] = {}
    xfs: List[int] = []

    records: List[Tuple[int, bytes]] = []
    pos = 0
    while pos + 4 <= len(workbook):
        record_type, length = struct.unpack("<HH", workbook[pos: pos + 4])
        data = workbook[pos + 4: pos + 4 + length]
        records.append((record_type, data))
        pos += 4 + length

    index = 0
    while index < len(records):
        record_type, data = records[index]
        if record_type == 0x00FC:
            while index + 1 < len(records) and records[index + 1][0] == 0x003C:
                data += records[index + 1][1]
                index += 1
            sst = _parse_sst(data)
        elif record_type == 0x0085:
            bof_pos = struct.unpack("<L", data[:4])[0]
            name, _ = _decode_short_unicode(data, 6)
            sheet_offsets.append((name, bof_pos))
        elif record_type == 0x041E:
            format_index = struct.unpack("<H", data[:2])[0]
            fmt, _ = _decode_short_unicode(data, 2)
            formats[format_index] = fmt
        elif record_type == 0x00E0:
            if len(data) >= 4:
                xfs.append(struct.unpack("<H", data[2:4])[0])
        index += 1

    built_in_date_formats = {
        14, 15, 16, 17, 22, 27, 30, 36, 45, 46, 47, 50, 57,
    }

    sheets: Dict[str, List[List[str]]] = {}
    for sheet_name, offset in sheet_offsets:
        rows: Dict[int, Dict[int, str]] = {}
        pos = offset
        while pos + 4 <= len(workbook):
            record_type, length = struct.unpack("<HH", workbook[pos: pos + 4])
            data = workbook[pos + 4: pos + 4 + length]
            pos += 4 + length
            if record_type == 0x000A:
                break
            if record_type == 0x0203:
                row, col, xf = struct.unpack("<HHH", data[:6])
                number = struct.unpack("<d", data[6:14])[0]
                fmt_idx = xfs[xf] if xf < len(xfs) else -1
                if fmt_idx in built_in_date_formats or any(token in formats.get(fmt_idx, "").lower() for token in ("yy", "dd", "mm", "h", "s")):
                    value = excel_serial_to_iso(number)
                else:
                    value = str(int(number)) if number.is_integer() else str(number)
                rows.setdefault(row, {})[col] = value
            elif record_type == 0x027E:
                row, col, _xf, rk = struct.unpack("<HHHI", data[:10])
                value = _rk_to_float(rk)
                rows.setdefault(row, {})[col] = str(int(value)) if value.is_integer() else str(value)
            elif record_type == 0x00BD:
                row, first_col = struct.unpack("<HH", data[:4])
                last_col = struct.unpack("<H", data[-2:])[0]
                cursor = 4
                for col in range(first_col, last_col + 1):
                    _xf, rk = struct.unpack("<HI", data[cursor: cursor + 6])
                    cursor += 6
                    value = _rk_to_float(rk)
                    rows.setdefault(row, {})[col] = str(int(value)) if value.is_integer() else str(value)
            elif record_type == 0x00FD:
                row, col, _xf, sst_idx = struct.unpack("<HHHI", data[:10])
                value = sst[sst_idx] if sst_idx < len(sst) else ""
                rows.setdefault(row, {})[col] = value
            elif record_type == 0x0204:
                row, col, _xf = struct.unpack("<HHH", data[:6])
                length_text = struct.unpack("<H", data[6:8])[0]
                value = data[8: 8 + length_text].decode("latin1", errors="ignore")
                rows.setdefault(row, {})[col] = value

        rendered: List[List[str]] = []
        for row_index in sorted(rows):
            row = rows[row_index]
            width = max(row) + 1
            rendered.append([str(row.get(index, "")).strip() for index in range(width)])
        sheets[sheet_name or "Sheet1"] = rendered
    return sheets
