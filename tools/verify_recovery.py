"""원본 코드 객체를 실행하지 않고 복원 소스의 컴파일 결과와 비교해요."""

import argparse
import dis
import hashlib
import json
import marshal
from pathlib import Path
import sys
import types
import zipfile

FIELDS = (
    "co_code", "co_exceptiontable", "co_names", "co_varnames", "co_freevars",
    "co_cellvars", "co_argcount", "co_posonlyargcount", "co_kwonlyargcount",
    "co_flags", "co_stacksize", "co_name", "co_qualname",
)


def class_line_constants(code):
    instructions = list(dis.get_instructions(code))
    return {
        instructions[index - 1].arg
        for index, instruction in enumerate(instructions)
        if instruction.opname == "STORE_NAME"
        and instruction.argval == "__firstlineno__"
        and instructions[index - 1].opname == "LOAD_CONST"
    }


def verify(original, recovered, label, results):
    differences = [field for field in FIELDS if getattr(original, field) != getattr(recovered, field)]
    original_lines = class_line_constants(original)
    recovered_lines = class_line_constants(recovered)
    if len(original.co_consts) != len(recovered.co_consts):
        differences.append("co_consts length")
    for index, (a, b) in enumerate(zip(original.co_consts, recovered.co_consts)):
        if isinstance(a, types.CodeType) and isinstance(b, types.CodeType):
            verify(a, b, f"{label}/{a.co_name}@const{index}", results)
        elif index in original_lines and index in recovered_lines:
            pass
        elif type(a) is not type(b) or a != b:
            differences.append(f"co_consts[{index}]")
    results.append({
        "code": label, "passed": not differences, "differences": differences,
        "original_bytecode_sha256": hashlib.sha256(original.co_code).hexdigest(),
        "recovered_bytecode_sha256": hashlib.sha256(recovered.co_code).hexdigest(),
        "exception_table_equal": original.co_exceptiontable == recovered.co_exceptiontable,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if sys.version_info[:3] != (3, 13, 0):
        raise SystemExit("원본과 같은 CPython 3.13.0으로 검증해 주세요. 앱 실행은 Python 3.13.x를 사용할 수 있어요.")
    project = Path(__file__).resolve().parents[1]
    results = []
    modules = []
    with zipfile.ZipFile(project / "recovery" / "reference_bytecode.zip") as archive:
        for entry in sorted(archive.namelist()):
            if not entry.endswith(".pyc"):
                continue
            relative = Path(entry).with_suffix(".py")
            original = marshal.loads(archive.read(entry)[16:])
            source = (project / relative).read_text(encoding="utf-8")
            recovered = compile(source, original.co_filename, "exec", dont_inherit=True, optimize=0)
            verify(original, recovered, relative.as_posix(), results)
            modules.append(relative.as_posix())
    report = {
        "python": sys.version,
        "modules": modules,
        "total": len(results),
        "passed": sum(row["passed"] for row in results),
        "compared": list(FIELDS) + ["co_consts (recursive, type-sensitive)"],
        "excluded": ["co_filename", "co_firstlineno", "co_linetable", "class __firstlineno__ source location constant"],
        "results": results,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"모듈 {len(modules)}개, 코드 객체 {len(results)}개 중 {report['passed']}개 일치")
    for row in results:
        if not row["passed"]:
            print(row["code"], row["differences"])
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
