"""The descriptor is declared twice (acc_pkg.sv and export.FIELDS): both must list the same fields,
widths and order (spec 8), or the RTL would decode desc.hex wrongly."""
import re

import cifar
import export


def test_desc_t_matches_export_fields():
    src = (cifar.ROOT / "rtl" / "core" / "acc_pkg.sv").read_text()
    body = re.search(r"typedef struct packed \{(.*?)\} desc_t;", src, re.S).group(1)
    fields = []
    for m in re.finditer(r"logic\s*(?:\[(\d+):0\])?\s+(\w+);", body):
        fields.append((m.group(2), int(m.group(1)) + 1 if m.group(1) else 1))
    assert fields == export.FIELDS
    assert sum(w for _, w in fields) == export.DESC_BITS == 80
