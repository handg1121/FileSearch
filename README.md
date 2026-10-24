# FileSearch 복원 프로젝트

기존 `FileSearch.exe`에서 복원한 Windows용 Python 프로젝트예요. `main.py`, `collector`, `common`, `searcher`의 원래 모듈 구성을 살렸어요. GitHub 접속 없이 폴더를 열어 코드를 수정하고 실행할 수 있어요.

## 실행

Python **3.13, Windows 64비트**, **PySide6 6.12.0**, **olefile 0.47**을 사용해요. SQLite는 Python에 포함되어 있어 따로 설치하지 않아요. 원본은 CPython 3.13.0이었어요. Python이 없다면 [공식 배포 페이지](https://www.python.org/downloads/windows/)에서 설치해 주세요.

프로젝트 폴더에서 PowerShell을 열고 다음 명령을 실행해요.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Python 실행 명령이 `python`이라면 첫 줄을 `python -m venv .venv`로 바꿀 수 있어요. 가상환경을 활성화하지 않고 실행하는 방식이라 PowerShell 실행 정책 변경은 필요하지 않아요.

처음 패키지를 설치할 때는 PyPI 연결이 필요해요. GitHub, 원본 EXE, 추출한 바이트코드는 앱 실행에 필요하지 않아요. 설치 후에는 `run.cmd`로도 실행할 수 있어요.

## 프로젝트 구성

```text
main.py                       프로그램 시작, 메인 화면
collector/
  collector.py                파일 모으기 창과 전체 작업 흐름
  type_selector_script.py     파일 탐색·복사·이동·중복·작업 복구
  workers.py                  작업 스레드
  type_selector.py            파일 유형 선택
  progress_dialog.py          진행 창
  summary_dialog.py           찾은 파일 요약과 실행 확인
  result_dialog.py            결과와 실패 목록
common/
  settings.py                 사용자 설정
  file_actions.py             파일·탐색기 열기
  widgets.py                  공통 위젯과 화면 스타일
searcher/
  filename_search.py          파일명 검색과 정렬
  search_pipeline.py          run 오케스트레이터, 본문 부분 검색
  metadata.py                 파일 메타데이터 읽기·비교
  body_cache.py               SQLite 메타데이터 읽기·본문 캐시 동기화
  body_extractors.py          HWP·HWPX·TXT 본문 추출
  workers.py                  검색 작업 스레드
  search_bar.py               검색 조건
  result_table.py             검색 결과
  preview_panel.py            파일 정보 미리보기
tests/                        복원 후 추가한 회귀·GUI 검사
tools/verify_recovery.py       원본 바이트코드와 소스 비교
recovery/                     검증 결과, 원본 비교 자료, 화면 캡처
FileSearch.spec               새로 작성한 EXE 빌드 설정
```

`collector`, `common`, `searcher`에는 원본처럼 `__init__.py`도 있어요. 모든 앱 로직은 일반 `.py` 소스이며, 숨긴 바이트코드를 실행하는 로더로 대체하지 않았어요.

## 검증 결과

아래 검증 결과와 `recovery/`의 자료는 최초 복원 당시의 기록이에요. 이후 기능을 수정한 소스는 원본 바이트코드와 달라질 수 있어요.

- 원래 앱 모듈 **18개**를 모두 복원했어요.
- 모듈·클래스·함수·중첩 함수 등 **코드 객체 166개**의 실행 바이트코드와 예외 처리 테이블이 원본과 바이트 단위로 일치했어요.
- 상수, 함수 인자, 지역·전역·클로저 이름도 비교했어요. 소스 위치 정보와 클래스의 `__firstlineno__` 값은 제외했어요.
- 임시 폴더를 사용하는 회귀 테스트 **17개**를 통과했어요.
- 화면 구성, 검색, 선택·정렬, 설정 저장, 실제 작업 스레드의 탐색·복사, 취소 신호 등 GUI 검사 **23개 항목**을 통과했어요.
- `FileSearch.spec`로 Windows EXE를 재빌드하는 데 성공했어요. 화면·동작 검사는 복원 소스로 실행했으며, 재빌드 EXE의 별도 화면 동작 검사는 하지 않았어요.

자세한 범위와 원본 정보는 [복원 기록](recovery/복원기록.md)에 있어요.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

GUI 검사는 화면을 띄우지 않는 Qt 모드로 실행하고, 지정한 작업 폴더에 테스트 파일과 캡처를 만들어요. 실제 사용할 자료 폴더를 지정하지 말고 아래처럼 전용 테스트 폴더를 사용해요.

```powershell
.\.venv\Scripts\python.exe tests/gui_smoke.py --workspace .test-tmp/gui --artifacts .test-tmp/screenshots
.\.venv\Scripts\python.exe tests/gui_body_smoke.py --workspace .test-tmp/body-gui --artifacts .test-tmp/body-screenshots
```

원본과 같은 **CPython 3.13.0** 환경에서 바이트코드 검증을 재현할 수 있어요. 복원 소스를 수정하면 비교 결과가 달라지는 것이 정상이에요.

```powershell
.\.venv\Scripts\python.exe tools/verify_recovery.py --report .test-tmp/verification.json
```

## EXE 다시 만들기

코드를 저장하고 프로젝트 루트의 **`build.bat`를 더블클릭**하면 현재 소스로 EXE를 다시 만들어요. 실행 중인 `dist/FileSearch/FileSearch.exe`는 먼저 닫아 주세요. 빌드가 끝나면 성공/실패 메시지를 확인할 수 있도록 창을 열어 둬요.

```powershell
.\build.bat
```

결과는 **`dist/FileSearch/FileSearch.exe`**예요. 이전 EXE에 소스 변경이 자동으로 반영되는 것은 아니며, 수정 후 배치파일을 다시 실행해야 해요. `run.cmd`는 빌드 없이 Python 소스를 바로 실행할 때 사용해요.

배치파일은 `.venv`를 사용하고, 없으면 프로젝트 내부 `.build-python` 또는 설치된 `py -3.13`으로 가상환경을 만들어요. 필요한 패키지를 `requirements-build.txt`에 맞춰 준비한 뒤 `FileSearch.spec`로 새로 빌드해요. 최초 설치나 패키지가 추가된 경우 인터넷 연결이 필요할 수 있어요. 자동 실행에서는 `build.bat --no-pause`로 마지막 대기를 생략할 수 있어요.

현재 PC에는 `E:\Projects\FileSearch\.build-python`에 Python 3.13.0을 준비했어요. `.venv`가 이 Python을 사용하므로 두 폴더를 유지해 주세요. 시스템 Python 설치나 PATH 변경 없이 빌드할 수 있어요. `.build-python`, `.venv`, `build`, `dist`는 Git에서 제외해요. 다른 PC에서 소스를 내려받으면 Python 3.13 64비트를 설치하거나 별도로 빌드 환경을 준비해야 해요.

빌드 설정은 DLL 검색 경로를 프로젝트 Python과 Windows 폴더로 한정해요. 다른 프로그램이 PATH에 추가한 동명의 ICU DLL 등이 실행파일에 섞이지 않도록 하기 위한 설정이에요.

수동으로 빌드할 때는 다음 명령도 사용할 수 있어요.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm FileSearch.spec
```

결과는 `dist/FileSearch/FileSearch.exe`예요. 실행 파일과 옆의 `_internal` 폴더를 함께 배포해요. 원본 `.spec` 파일이 배포본에 없어서, 기존 배포 구조에 맞춰 새로 작성했어요. 새 EXE 자체의 해시가 이전 EXE와 같다는 뜻은 아니에요.

## 본문 검색 흐름

`MainWindow.run_search()`는 체크박스 값을 `SearchRequest`에 담아 작업 스레드를 시작하고, 완료된 `SearchResult`를 화면에 전달해요. 실제 분기는 `searcher/search_pipeline.py`의 `run()`에서 처리해요.

| 함수 | 역할과 반환값 |
| --- | --- |
| `run` | 파일명/본문 분기, 캐시 동기화, 결과 병합. 결과·실패 목록·캐시 처리 건수·취소 여부를 반환해요. |
| `read_file_metadata` | 하위 폴더의 전체 경로·파일명·수정 시각(ns)·크기를 읽고, 탐색 실패도 함께 반환해요. |
| `read_sqlite_metadata` | 현재 검색 폴더에 속한 캐시 메타데이터와 처리 상태만 읽어요. 본문은 읽지 않아요. |
| `compare_metadata` | 신규·수정·재시도·유지·삭제로 분류해요. DB를 변경하지 않아요. |
| `extract_file_body` | 형식별로 전체 본문을 추출해요. 실패나 취소를 빈 본문으로 바꾸지 않아요. |
| `sync_body_cache` | 신규·수정·실패 파일의 본문을 읽고 메타데이터와 함께 저장해요. 사라진 파일의 캐시도 정리해요. |
| `search_keyword_body` | 정상 캐시를 한 파일씩 읽고, 문구가 포함된 파일 목록과 본문 발췌를 반환해요. |

본문 캐시는 `%APPDATA%\FileSearch\body_cache.sqlite3`에 저장해요. 검색 루트와 전체 파일 경로를 식별자로 쓰므로 하위 폴더에 이름이 같은 파일도 구분해요. 본문 전문을 TEXT로 저장하며 FTS/단어 색인은 만들지 않아요. EXE를 빌드하면 SQLite와 HWP 읽기 모듈도 함께 포함해요.

- 첫 본문 검색에서는 선택한 종류·날짜 조건에 해당하는 지원 파일을 읽어요. 이후에는 수정 시각과 크기가 같은 정상 캐시를 재사용해요. 원본 본문 대신 캐시 본문을 매번 순회하는 방식이에요.
- 메타데이터 탐색은 필터와 무관하게 전체 하위 폴더를 확인해요. 필터 때문에 결과에서 빠진 파일을 삭제된 것으로 판정하지 않아요. 심볼릭 링크와 Windows 정션은 따라가지 않아요.
- 폴더 접근이나 파일 상태 확인에 실패하면 그 검색에서는 삭제 정리를 보류해요. 다른 검색 루트의 캐시는 삭제하지 않아요.
- 본문을 읽기 전후에 파일 상태를 다시 확인해요. 중간에 바뀌었거나 추출에 실패하면 이전 본문을 검색 결과에 쓰지 않고, 다음 검색에서 다시 시도해요. 실제 빈 문서는 정상 캐시로 저장해요.
- 검색 취소 시 이미 저장한 캐시는 유지하고, 불완전한 검색 결과는 화면에 표시하지 않아요. 진행 창에서 취소할 수 있고 오류 상세는 결과 상태 문구에 마우스를 올리면 보여요.
- 수정 시각과 크기를 모두 원래대로 유지한 내용 변경은 감지하지 못해요. 파일 이름 변경·이동은 기존 경로 삭제와 새 경로 추가로 처리해요.

## 검색 규칙과 지원 범위

- **파일명만**: 기존처럼 띄어쓰기로 나눈 단어가 파일명에 모두 있는지 확인해요.
- **파일 내용만**: Ctrl+F처럼 입력 전체의 부분 문자열을 찾아요. `계약금`은 `선급계약금을`에서도 찾아요. 대소문자는 구분하지 않고 한글 자모 표현은 NFC로 통일해요.
- 본문의 공백·탭·문단 구분은 보존해요. `계약금을 지불한다`는 연속된 그 문구를 찾으며, 중간에 다른 단어나 줄바꿈이 있으면 일치하지 않아요. `%`, `_`, `*`, 따옴표는 일반 글자예요.
- **둘 다 선택**: 파일명 또는 본문 중 하나라도 일치하면 표시하고, 경로 기준으로 중복을 제거해요.
- 검색어가 비어 있으면 이름 검색은 필터에 맞는 전체 파일, 본문 검색은 정상적으로 읽은 지원 파일을 보여 줘요.
- **HWP 5.x**: BodyText의 모든 문단 레코드를 읽어요. 표·글상자·각주 등의 텍스트도 포함해요. `PrvText` 미리보기만 읽는 방식은 아니에요. 암호·배포용·이전 HWP 형식은 지원하지 않아요.
- **HWPX**: ZIP 내부 본문 구역의 문단·텍스트 런을 순서대로 읽어요. 레이아웃을 재현하는 기능은 아니에요.
- **TXT**: UTF-8(BOM 포함), BOM이 있는 UTF-16, CP949를 지원해요.
- PDF·Word·Excel·PowerPoint·이미지 본문과 OCR은 아직 지원하지 않아요. 이 파일들은 파일명 검색이 가능하고, 본문 검색에서는 미지원 건수로 안내해요.
- 이미지에만 들어 있는 글자와 임베디드 첨부 파일의 내용은 추출하지 않아요. 처리 한도는 구역/텍스트 데이터 64 MiB, 문서 본문 약 3,355만 글자이며 초과 파일은 실패로 안내해요.

이번 변경은 코어 회귀 검사 40개(기존 17개 포함), 기존 GUI 검사 23개, 본문 GUI 검사 18개를 통과했어요. 본문 GUI 검사는 실제 작업 스레드의 검색·미리보기·캐시 재사용·취소 후 재시도를 포함해요. 공개 [pyhwp 시험 문서](https://github.com/mete0r/pyhwp/tree/master/tests/hwp5_tests/fixtures) 8개도 별도로 확인했으며, 일반 문서 6개를 추출하고 암호·배포용 문서 2개는 해당 사유로 제외했어요. 공개 샘플 파일은 프로젝트에 포함하지 않았어요.

현재 `build.bat`로 Windows EXE를 생성했고, 포함된 앱 모듈 23개의 코드가 현재 소스와 일치하는지 확인했어요. `_sqlite3.pyd`, `sqlite3.dll`, `olefile` 및 새 검색 모듈도 포함해요. EXE는 별도 테스트 설정의 화면 없는 Qt 모드로 직접 실행하여 Qt와 SQLite 초기화 및 시작 오류가 없음을 확인했어요. 검색·미리보기·취소의 상세 동작은 Python 소스 GUI 검사로 검증했어요.

## 현재 기능 상태

- 기본 저장 위치는 `D:\모은파일`이에요. 파일 모으기 창에서 변경할 수 있어요.
- 설정은 `%APPDATA%\FileSearch\settings.json`에 저장해요.
- 파일명 검색과 SQLite 캐시를 사용하는 본문 검색을 연결했어요. 본문 검색을 켜면 문구 검색 안내와 지원 형식을 표시해요.
- 태그 표시 숫자와 일부 메뉴는 화면용 상태를 유지했어요.
- 본문 검색으로 찾은 파일을 선택하면 일치한 문구 주변을 보여 줘요. 검색 결과는 기존처럼 처음 500개만 표시해요.
- 원본의 복사·이동·중단 복구 로직을 그대로 보존했어요. 복구 로직에서 확인한 기존 제약은 복원 기록에 적었어요.

원래 주석·공백·작성 이력까지 되살린 것은 아니에요. 남아 있던 docstring, 한글 문구와 스타일 문자열은 보존했어요. README, 테스트, `pyproject.toml`, 패키지 목록, 빌드 설정은 복원 후 작업을 이어갈 수 있도록 새로 추가했어요.
