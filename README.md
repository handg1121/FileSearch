# FileSearch 복원 프로젝트

기존 `FileSearch.exe`에서 복원한 Windows용 Python 프로젝트예요. `main.py`, `collector`, `common`, `searcher`의 원래 모듈 구성을 살렸어요. GitHub 접속 없이 폴더를 열어 코드를 수정하고 실행할 수 있어요.

## 실행

Python **3.13, Windows 64비트**와 **PySide6 6.12.0**을 사용해요. 원본은 CPython 3.13.0이었어요. Python이 없다면 [공식 배포 페이지](https://www.python.org/downloads/windows/)에서 설치해 주세요.

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
```

원본과 같은 **CPython 3.13.0** 환경에서 바이트코드 검증을 재현할 수 있어요. 복원 소스를 수정하면 비교 결과가 달라지는 것이 정상이에요.

```powershell
.\.venv\Scripts\python.exe tools/verify_recovery.py --report .test-tmp/verification.json
```

## EXE 다시 만들기

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm FileSearch.spec
```

결과는 `dist/FileSearch/FileSearch.exe`예요. 실행 파일과 옆의 `_internal` 폴더를 함께 배포해요. 원본 `.spec` 파일이 배포본에 없어서, 기존 배포 구조에 맞춰 새로 작성했어요. 새 EXE 자체의 해시가 이전 EXE와 같다는 뜻은 아니에요.

## 원본에서 그대로 유지한 상태

- 기본 저장 위치는 `D:\모은파일`이에요. 파일 모으기 창에서 변경할 수 있어요.
- 설정은 `%APPDATA%\FileSearch\settings.json`에 저장해요.
- 파일 내용 검색과 태그 기능은 원래 미완성이에요. 태그 표시 숫자와 일부 메뉴도 화면용 상태를 유지했어요.
- 본문 미리보기는 안내 문구만 있고, 검색 결과는 처음 500개만 표시해요.
- 원본의 복사·이동·중단 복구 로직을 그대로 보존했어요. 복구 로직에서 확인한 기존 제약은 복원 기록에 적었어요.

원래 주석·공백·작성 이력까지 되살린 것은 아니에요. 남아 있던 docstring, 한글 문구와 스타일 문자열은 보존했어요. README, 테스트, `pyproject.toml`, 패키지 목록, 빌드 설정은 복원 후 작업을 이어갈 수 있도록 새로 추가했어요.
