# FileSearch

Windows에서 파일을 모으고, 파일명·본문·태그로 검색하는 데스크톱 프로그램이에요.
Python과 PySide6로 개발하며, 일반 사용자는 Python 설치 없이 배포된 프로그램을 사용할 수 있어요.

## 현재 상태

- 소스 버전은 `updater/config.py`에서 관리해요.
- 0.2.5부터 **설치 없이 바로 실행하는 `FileSearch.exe` 하나**로 배포해요.
- 단일 EXE 전환분은 빌드·정적 코드·산출물 점검을 진행했어요. 실제 실행·업데이트는 사용자가 수동으로 확인해요.
- 이전 개발 과정과 검증 기록은 [개발·복원 기록](docs/HISTORY.md)에 보관해요. 현재 사용법과 빌드 절차는 이 README를 기준으로 봐 주세요.

## 주요 기능

| 기능 | 지원 범위 |
|---|---|
| 파일 모으기 | 선택한 위치에서 파일 유형별로 복사·이동하고 진행 상황을 확인해요. |
| 파일명 검색 | 검색어와 파일 유형·수정일 조건으로 찾아요. **전체 파일** 버튼은 검색어를 비우고 현재 조건으로 검색해요. |
| 본문 검색 | HWP 5.x·HWPX·TXT를 지원해요. 추출 결과를 캐시해서 다음 검색에서 재사용해요. |
| 이미지 글자 검색 | PNG·JPEG·BMP·TIFF·정지 WebP의 한국어·영어 OCR을 지원해요. OCR 엔진과 언어 모델을 포함해요. |
| 태그 | 태그 부착·제거·색상·이름 수정, 태그명 검색과 태그별 파일 보기를 지원해요. |
| 중복 파일 | 파일 내용 기반의 중복 검사와 정리를 지원해요. |
| 결과 목록 | 기본 50개씩 보여 주고, 10·30·50·100·300·500개를 선택할 수 있어요. 전체 결과를 정렬한 뒤 페이지로 나눠요. |
| 자동 업데이트 | GitHub Releases에서 새 버전을 받아 앱 종료 후 적용해요. |

### 현재 제한

- **최근 추가** 메뉴는 아직 전용 동작이 연결되지 않았어요.
- PDF·Word·Excel·PowerPoint는 파일명·태그명으로 검색할 수 있지만 본문 추출은 지원하지 않아요.
- 스캔 PDF와 문서 안에 삽입된 이미지의 OCR은 지원하지 않아요.
- 암호가 설정된 HWP, 배포용 HWP, HWP 5.x 이전 형식은 본문 검색에서 제외돼요.
- 파일 이동 확인은 같은 파일명을 기준으로 후보를 찾으므로 파일명까지 바뀐 경우는 추적하지 않아요.

## 다운로드와 바로 실행

배포된 버전은 [GitHub Releases](https://github.com/handg1121/FileSearch/releases)에서 확인해요.

**[최신 FileSearch.exe 다운로드](https://github.com/handg1121/FileSearch/releases/latest/download/FileSearch.exe)**

Windows 10/11 64비트용이에요. 0.2.5의 실행 파일은 약 108MB예요.

1. `FileSearch.exe`를 원하는 곳에 저장해요.
2. 더블클릭하면 프로그램이 열려요. 설치 화면, Python 설치, 관리자 권한이 필요하지 않아요.
3. 다음에도 같은 EXE를 실행해요. 앱 안의 **업데이트 확인**으로 새 버전을 받을 수 있어요.

EXE에 프로그램과 OCR 구성요소가 모두 들어 있어 첫 실행에 추가 다운로드는 필요하지 않아요.
처음 실행할 때 필요한 파일을 아래 사용자 캐시에 자동으로 준비하므로 창이 열리기까지 잠시 걸릴 수 있어요.
EXE를 다른 폴더로 옮기거나 이름을 바꿔도 같은 Windows 계정에서는 기존 캐시와 데이터를 사용해요.

```text
%LOCALAPPDATA%\FileSearch\Runtime\
```

시작 메뉴 바로가기나 Windows 설치 앱 등록은 만들지 않아요. 실행 파일 옆에 보조 폴더를 둘 필요도 없어요.
단일 EXE 배포이지만 실행 캐시는 디스크에 남아요. 사용자 데이터까지 EXE 안에 저장하는 방식은 아니에요.
사용을 그만둘 때는 프로그램을 종료한 뒤 EXE와 위 실행 캐시를 지울 수 있어요.
설정·태그와 모은 파일은 별도 위치에 있어 그대로 남아요.

### 이전 배포본에서 전환

0.2.0~0.2.3은 폴더 전체를 유지해야 하는 ZIP 배포본이고, 0.2.4의 `FileSearch-Setup-0.2.4.exe`는 설치형이에요.
기존 프로그램을 종료하고 최신 단일 `FileSearch.exe`를 받아 실행하면 같은 Windows 계정의 설정·태그·모은 파일을 사용해요.
기존 버전에서 앱 내부 업데이트만 하면 앱 기능은 갱신되지만 배포 형태는 그대로예요.
설치형에서 단일 EXE로 전환하려면 새 EXE를 직접 받아 주세요. 기존 설치형은 필요하면 Windows의 설치된 앱에서 제거할 수 있어요.

### 기본 사용 흐름

1. **파일 모으기**에서 검색할 파일을 모으고 저장 위치를 정해요.
2. 검색 항목을 선택한 뒤 검색하거나, **전체 파일**을 눌러 현재 조건에 해당하는 목록을 봐요.
3. 파일을 선택하면 미리보기가 표시돼요. 태그를 붙일 때는 왼쪽 체크박스로 파일을 선택해요.
4. 결과 아래에서 표시 개수와 페이지를 바꿔요. 페이지를 넘기면 체크 선택과 미리보기가 초기화돼요.
5. 더블클릭으로 파일을 열고, 우클릭 메뉴에서 파일이나 폴더를 열 수 있어요.

## 사용자 데이터와 프로그램 파일

| 내용 | 저장 위치 |
|---|---|
| 설정 | `%APPDATA%\FileSearch\settings.json` |
| 태그·본문 캐시 등 데이터베이스 | `%APPDATA%\FileSearch\body_cache.sqlite3` |
| 모은 파일 | 사용자가 지정한 저장 폴더. 기본값은 `D:\모은파일`이에요. |
| 단일 EXE의 실행 캐시 | `%LOCALAPPDATA%\FileSearch\Runtime` |
| 업데이트 파일과 버전 상태 | 실행 캐시 아래 `.updates`와 `versions` |
| 일반 개발 빌드의 실행 캐시 | `%LOCALAPPDATA%\FileSearch\Development\<빌드 해시>` |

업데이트와 실행 캐시 준비는 사용자 설정·태그·모은 파일을 삭제하지 않아요.
실행 캐시를 지우면 다음 실행에서 EXE에 포함된 기본 버전부터 다시 준비해요.
이전 설치형의 프로그램 위치는 `%LOCALAPPDATA%\Programs\FileSearch`이며 새 실행 캐시와 별개예요.

## 개발 환경 준비

- Windows 10/11 64비트
- Python **3.13 64비트**
- 처음 의존성과 빌드 도구를 준비할 때 인터넷 연결

PowerShell에서 저장소를 받은 폴더로 이동해 실행해요.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

가상환경을 준비한 뒤에는 `run.cmd`로도 소스 버전을 실행할 수 있어요.
런타임 의존성은 `requirements.txt`, 빌드 의존성은 `requirements-build.txt`에 고정되어 있어요.
OCR 엔진·모델은 `vendor/tesseract`에 포함되며 빌드 전에 `manifest.json`의 해시와 대조해요.

## 배치로 단일 실행 EXE 만들기

```powershell
.\build.bat
```

배치는 Python 환경과 의존성을 준비하고, 앱·OCR을 포함한 단일 실행 EXE를 만들어요.
일반 빌드에는 GitHub 인증이나 비밀 서명키가 필요하지 않아요.
반복 빌드는 시간별 새 폴더에 저장해서 기존 빌드와 설치본을 덮어쓰지 않아요.

```text
dist/development/<버전>-<빌드시간>/
  FileSearch.exe       설치 없이 실행하는 단일 파일
  embedded-payload/    EXE에 내장하는 앱 ZIP과 무결성 정보 (개발용)
  folder-build/        호환성 점검용 폴더 빌드 (개발용)
  build-info.json      산출물 크기·SHA-256 기록
```

자동화 환경에서 마지막 대기 화면을 생략하려면 `build.bat --no-pause`를 사용해요.
빌드 자체는 프로그램 실행, 설치, 테스트, GitHub 업로드를 수행하지 않아요.

빌드는 PyInstaller를 사용하며 NSIS나 설치 컴파일러는 필요하지 않아요.
일반 개발 빌드는 같은 버전을 다시 빌드해도 이전 코드를 실행하지 않도록 빌드 해시별 실행 캐시를 사용해요.
단, 개발 빌드도 기본 설정에서는 같은 Windows 계정의 사용자 데이터를 사용하므로 개발 시 별도 프로필을 지정해 주세요.

## 저장소와 Releases의 역할

```text
저장소의 소스 수정 → 배치 빌드 → Releases 게시 → EXE 바로 실행·자동 업데이트
```

- **저장소**: 소스 코드, 빌드 스크립트, 문서와 검증 코드를 관리해요.
- **Releases**: 바로 실행하는 EXE와 앱이 자동으로 사용할 업데이트 파일을 게시해요.
- `dist/`, `build/`, `.venv/`, `.build-tools/`는 `.gitignore`로 제외해요. 생성된 EXE·ZIP을 Git 이력에 추가하지 않아요.
- `vendor/tesseract`는 고정된 OCR 의존성이에요. 매번 생성되는 앱 빌드 결과와 구분하며, 엔진을 갱신할 때만 변경해요.

사용자가 다운로드하는 파일은 `FileSearch.exe` 하나예요. Releases에는 자동 업데이트를 위해 다음 세 파일을 게시해요.

| 파일 | 용도 |
|---|---|
| `FileSearch.exe` | 다운로드한 뒤 더블클릭하면 바로 실행돼요. |
| `FileSearch-update-<버전>-win64.zip` | 실행 중인 앱이 백그라운드에서 받는 새 앱 파일이에요. 사용자가 직접 풀 필요는 없어요. |
| `update.json` | 버전·다운로드 주소·크기·SHA-256·전자서명을 담은 업데이트 정보예요. |

## 배포 담당자용 빌드와 게시

1. `updater/config.py`의 `VERSION`을 새 버전으로 올려요. 이미 배포한 버전의 파일을 덮어쓰지 않아요.
2. 배포용 서명키가 있는 개발 PC에서 다음 명령을 실행해요.

```powershell
.\build.bat --release
```

결과는 `dist/releases/<버전>/`에 생성돼요. 호환성 점검용 폴더 빌드는 `dist/FileSearch-<버전>/`에 있어요.
이미 같은 버전의 배포 출력이 있으면 빌드를 중단해요. 실패한 미게시 빌드를 다시 만들 때는 해당 출력 폴더를 별도로 보관한 뒤 다시 빌드해요.
생성된 `build-info.json`은 로컬 검토용이며, 게시 도구는 위 표의 세 파일만 업로드해요.

게시할 정확한 소스 커밋과 릴리스 설명 파일을 준비해요. 실제 실행·업데이트 확인 여부는 릴리스 설명에 명시해요.

```powershell
.\.venv\Scripts\python.exe tools/publish_release.py --body-file release-notes.txt --target <소스커밋>
```

이 명령은 **초안 릴리스**를 만들어요. 공개 게시까지 하려면 `--publish`를 추가해요.
소스 커밋은 미리 GitHub 저장소에 올라가 있어야 해요. 게시 도구 자체는 소스 커밋을 push하지 않아요.
기존 Git Credential Manager 인증을 사용하며, 인증 정보를 프로그램에 포함하지 않아요.
초안의 업로드가 실패하면 불완전한 초안을 확인·정리한 뒤 다시 시도해요.

### 서명키

업데이트 서명키는 저장소 밖의 다음 파일에 Windows DPAPI로 암호화해 보관해요.

```text
%LOCALAPPDATA%\FileSearchRelease\signing-key.dpapi
```

개인키를 Git·Releases·실행 파일에 넣으면 안 돼요. 기존 사용자에게 업데이트를 제공하려면 같은 키를 계속 사용해야 해요.
DPAPI 파일은 Windows 사용자/환경에 묶여 있으므로 PC 교체나 재설치 전에 안전한 키 이전 계획이 필요해요.
저장소를 받은 다른 개발자는 일반 빌드를 사용할 수 있지만, 원래 배포 채널의 업데이트를 서명할 수는 없어요.
독립적인 배포를 만들려면 저장소 주소·공개키·서명키를 별도로 구성해야 해요.

이 전자서명은 자동 업데이트 파일을 검증하기 위한 것이에요. Windows의 EXE 코드 서명(Authenticode)과는 별개이며,
현재 EXE에 Authenticode 인증서 서명은 적용하지 않았어요.

## 자동 업데이트 동작

1. 앱이 실행 후 및 6시간마다 GitHub의 최신 `update.json`을 확인해요. **업데이트 확인** 버튼으로도 확인할 수 있어요.
2. 고정된 공개키로 서명을 확인하고 새 앱 ZIP을 내려받아 크기·SHA-256을 검증해요.
3. 업데이트가 준비되면 종료 후 적용해요. **지금 다시 시작**으로 바로 적용할 수도 있어요.
4. 실행기가 새 앱을 시작하고 시작 완료 응답을 받으면 업데이트를 확정해요. 시작에 실패하면 직전 버전으로 돌아가요.
5. Windows가 압축 해제 직후 폴더를 잠시 잠그면 최대 약 10초 동안 재시도해요. 계속 실패하면 기존 버전을 유지해요.

사용자 PC에서 소스 코드를 받거나 `build.bat`를 실행하지 않아요.
현재 데이터 구조와 실행기 프로토콜은 각각 1이에요. 호환되지 않는 업데이트는 거부해요.
앱용 업데이트 ZIP은 다운로드한 EXE 자체를 교체하지 않아요. 실행 캐시의 앱을 갱신하며,
다음에 같은 EXE를 실행해도 갱신된 앱을 열어요. 이전 EXE를 다시 실행해도 더 최신인 캐시 버전을 낮추지 않아요.
실행기 수정이 필요한 경우 최신 단일 EXE를 다시 받으면 돼요.
0.2.0~0.2.2 실행기의 반복적인 적용 실패도 수정된 실행기가 포함된 단일 EXE로 전환해 주세요.

### 단일 EXE의 구성

`Portable.spec`이 실행기와 앱 ZIP을 하나의 EXE로 묶어요. PyInstaller가 사용하는 임시 폴더와
영구 실행 캐시를 구분하며, 앱을 시작하기 전에 캐시 잠금·압축 경로·용량·SHA-256을 확인해요.
처음 준비한 기본 버전은 명시적으로 기록하고, 이후 업데이트는 기존 서명 검증·재시작·실패 시 복구 절차를 사용해요.
동일 EXE의 앱 준비가 반복 실행되지 않도록 이미 준비된 상태를 재사용해요.
PyInstaller 실행 구조는 [공식 문서](https://pyinstaller.org/en/stable/operating-mode.html#how-the-one-file-program-works)를 참고해 주세요.

## 프로젝트 구성

```text
main.py                 앱 시작과 메인 화면
collector/              파일 모으기와 진행·복구 처리
searcher/               파일명·본문 검색, 결과 목록, 미리보기
tagger/                 태그 저장·조회·수정과 UI
duplicates/             중복 파일 검사와 정리
ocr/                    OCR 실행과 추출 처리
common/                 설정·공통 위젯·파일 동작
updater/                업데이트 검증·적용·실행기·캐시 준비
portable_launch.py      단일 EXE의 진입점
Portable.spec           앱 전체를 포함한 단일 EXE 빌드 정의
Launcher.spec           개발자용 폴더 실행기 빌드 정의
installer/FileSearch.nsi 0.2.4 설치형 정의 (현재 기본 빌드에서 사용하지 않음)
tools/                  빌드·게시·무결성 점검 도구
tests/                  단위·GUI·배포본 검증 코드
vendor/tesseract/       고정된 OCR 엔진·모델·라이선스
docs/HISTORY.md         과거 개발·복원 기록
```

## 검증 명령과 수동 확인

빌드와 테스트는 별도예요. 개발자가 필요할 때 직접 실행해요.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe tests/gui_pagination_smoke.py --workspace C:\Temp\FileSearch-pagination --artifacts C:\Temp\FileSearch-pagination-results
.\.venv\Scripts\python.exe tests/frozen_update_smoke.py --workspace C:\Temp\FileSearch-frozen
```

검사 폴더에는 기존 사용자 자료가 없는 새 경로를 사용해요. 배포본 검사는 먼저 `--release` 빌드가 필요해요.
GUI 검사는 별도 프로필로 실행되며 실제 사용자 설정을 사용하지 않아요.
단일 EXE는 깨끗한 사용자 캐시에서 첫 실행, 재실행, EXE 이동·이름 변경, 중복 실행 차단,
자동 업데이트·재시작·실패 시 복구, 이전 EXE로 최신 캐시 실행을 수동으로 확인해 주세요.
기존 배포본에서 전환할 때 설정·태그·모은 파일이 유지되는지도 확인해 주세요.
기존 `frozen_update_smoke.py`는 개발자용 폴더 실행기 검사이며 단일 EXE의 최초 캐시 준비까지 검사하지 않아요.

## 외부 구성요소와 라이선스

- OCR 구성요소의 출처·해시·라이선스는 `vendor/tesseract/manifest.json`, `THIRD_PARTY_NOTICES.txt`, `licenses/`에 있어요.
- 0.2.4 설치형에 사용한 NSIS는 현재 단일 EXE 빌드에는 포함하지 않아요. 과거 설치형의 라이선스는 해당 설치 폴더에 있어요.
- 이 프로젝트 자체의 소스 재배포 라이선스는 아직 별도 `LICENSE` 파일로 명시하지 않았어요.
