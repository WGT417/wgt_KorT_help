# 작업 인계 메모 (2026-09-15)

다른 노트북에서 이어서 하기 위한 메모. 이 파일과 `work/concept-drafts/`가 현재 진행 상황의 전부다.

## 지금까지 끝난 것

- 개념 사전 세 영역(문법 51 · 문식성 16 · 문학 33 = 100개)을 모두 schema 2(요약 + 번호 절 + 굵은 소제목)로 다시 썼고, 근거 쪽(`pdf_page`, `status: verified`)을 전부 서재 개론서 본문을 읽고 확정했다. 판단절차·예와 반례·자주하는 오판은 어디에도 없다.
- 문학은 8개에서 33개로 늘렸다(시 10 · 소설 8 · 고전소설 5 · 고전시가 3 · 구비문학 1 · 문학교육 6).
- 검사기 `python scripts/check_concepts.py`, 단위 테스트 `python -m unittest discover -s tests`(49개), `node --check dist/app.js` 모두 통과한 상태로 커밋됨.

## 지금 하던 일: 문식성 항목 늘리기 (사용자 지시: "문식성도 늘려")

문식성은 독서 10 · 작문 4 · 화법 2로 얇아서, 개론서 5권(독서교육론 사회평론, 작문 교육론 사회평론, 작문 교육론 역락, 화법 교육론 역락, 국어교육을 위한 의사소통 이론)의 목차를 훑고 아래 목록을 잡았다. **화법부터** 쓰고 있었고, 17개 중 2개를 초안으로 써 둔 상태(아직 concepts에 병합 안 함).

### 화법 (`concepts/문식성-화법.json`) — 17개 예정

parent 이름: `화법의 기초`, `화법의 원리`(기존 politeness와 같음), `설득과 논증`, `담화 유형`(기존 discussion-vs-debate와 같음)

| 상태 | id | 라벨 | 근거 쪽(pdf_page) |
|---|---|---|---|
| 초안 완료 | speaking-principles/cooperative-principle | 협력의 원리와 대화 함축 | 의사소통 73–81, 화법 187–190 |
| 초안 완료 | speaking-discourse/conversation | 대화의 구조와 원리 | 화법 180–186, 191–193, 203–208 |
| 미작성 | speaking-process/listening | 듣기의 과정과 유형(추론적·비판적·공감적, 소극적/적극적 들어주기) | 화법 56–64, 207; 의사소통 57–66 |
| 미작성 | speaking-interaction/self-concept | 자아 개념과 의사소통(거울에 비친 자아, 중요한 타인, 자기실현적 예언) | 의사소통 15–24; 화법 92–94 |
| 미작성 | speaking-interaction/self-disclosure | 자기 노출(사회적 침투 이론, 조하리의 창, 불확실성 감소, 나-전달법) | 의사소통 41–50; 화법 94–95 |
| 미작성 | speaking-interaction/communication-anxiety | 의사소통 불안·말하기 불안(상황적/성향적, 생리적/인지적 원인, 체계적 둔감화) | 의사소통 26–35; 화법 99–104 |
| 미작성 | speaking-nonverbal/communication | 비언어 의사소통(준언어, 언어와의 관계, Burgoon 7유형, 근접학, 기능) | 의사소통 103–118, 120, 123–125; 화법 73–82 |
| 미작성 | speaking-culture/context-and-speech-community | 고맥락·저맥락 문화, 호프스테드 문화적 차원, 언어 공동체·담화 공동체 | 의사소통 135–150, 154–164 |
| 미작성 | speaking-persuasion/message-organization | 설득 메시지 조직(문제-해결, 문제-원인-해결, 동기화 단계), 내용 연결 표현, 발표 내용 구성 | 의사소통 169–182, 187–194; 화법 328–337 |
| 미작성 | speaking-persuasion/audience-analysis | 청자 분석과 정교화 가능성 모형, 핵심 변인(기존 입장·지적 수준·사전 지식·개인적 관련성), 일면/양면 메시지 | 의사소통 199–220; 화법 43–48 |
| 미작성 | speaking-persuasion/credibility-and-emotion | 화자의 공신력(에토스, 5차원, 신장 방법)과 감성적 소구(공포·유머·성적·온정) | 의사소통 223–230, 235–242; 화법 42–43 |
| 미작성 | speaking-argument/argumentation | 논증의 개념·조건·요소, 툴민 모형, 연역·귀납·인과·유추 논증과 오류, 기타 오류 | 의사소통 249–258, 260–271 |
| 미작성 | speaking-discourse/debate-strategy | 교육 토론 유형(CEDA·칼 포퍼·의회식·링컨 더글러스·퍼블릭 포럼), 입증 책임, 필수 쟁점, 입론·반대 신문·반박 | 의사소통 285–292, 296–306; 화법 275–280, 285–286, 290–291 |
| 미작성 | speaking-discourse/discussion-types | 토의 유형(패널·심포지엄·포럼·회의), 회의 원칙과 동의, 토의 일반 과정, 토의 문제 유형, 사회자 역할 | 화법 242–261 |
| 미작성 | speaking-discourse/negotiation | 협상(입장 vs 근원적 이해, 상호의존성과 세 딜레마, 유형, 5단계 절차, 갈등 처리) | 화법 294–308, 313–318 |
| 미작성 | speaking-discourse/interview | 면접(인상학적·기능적·스토리텔링·성찰적 관점, 질문 유형, 답변 전략) | 화법 216–233 |
| 미작성 | speaking-basics/nature-and-elements | 화법의 성격(구어적·상호교섭적·관계적·사회문화적)과 요소(화자·청자·메시지·장면), 인간 의사소통의 원리와 관점 | 화법 24–28, 32–47 |

기존 항목: `speaking-principles/politeness`(공손성·체면 포함), `speaking-discourse/discussion-vs-debate`(토의/토론 차이, 논제). 새 항목의 별칭이 이 둘과 겹치지 않게 하고 `confused_with`로 연결한다.

### 작문 (`concepts/문식성-작문.json`) — 11개 예정 (아직 쪽 미확정)

작문 이론의 전개(형식주의·인지주의·사회구성주의; 사회평론 2장, 역락 2장) / 대안적 작문 이론(대화주의·장르 중심·후기 과정; 사회평론 p.68–80) / 작문의 인지 과정 모형(Hayes&Flower, Bereiter&Scardamalia, Kellogg; 역락 3장) / 쓰기 동기·효능감·불안(역락 5장) / 과정별 쓰기 전략(사회평론 4장, 역락 8장) / 장르 중심·맥락 중심 작문 교수·학습(역락 7장, 사회평론 8장) / 정보 전달의 글쓰기(사회평론 10장) / 설득하는 글쓰기(11장) / 표현적 글쓰기(12장) / 학습을 위한 글쓰기(13장) / 작문 평가(사회평론 9장, 역락 12장) / 변화된 문식 환경·온라인 글쓰기(사회평론 5장, 역락 10장)

### 독서 (`concepts/문식성-독서.json`) — 8개 예정 (아직 쪽 미확정)

독서 능력·기능·전략과 독서 발달 단계(3장) / 텍스트의 유형·구조·난도(5장) / 정보 텍스트 교수학습(8장 1절) / 복합양식 텍스트 교수학습(8장 3절) / 독서 동기와 태도(9장 1절) / 독서토론 모형(9장 2절) / 학습독서·내용교과 독서(9장 3절) / 독서 평가(10장)

## 작업 방식

1. 쪽 가져오기 (한 번에 10쪽 이하, `pdf_page` 기준):
   ```
   python work/concept-drafts/pages_for.py speaking-principles/politeness --brief --no-sources --extra 0 --max-chars 1800 --pages "화법 교육론 역락:56,57,58" "국어교육을 위한 의사소통 이론:57,58"
   ```
   첫 인자는 아무 기존 항목 id면 된다(anchor). 문식성 5권 모두 `pdf_page = 책 쪽수 + 1`.
2. `work/concept-drafts/entries/<id를 하이픈으로>.json`에 schema 2 항목을 쓴다. 형식은 이미 있는 두 파일을 그대로 따른다. `_file` 키에 대상 파일명(`문식성-화법.json` 등)을 넣는다. `refs`는 `sources` 배열의 0부터 시작하는 인덱스. 굵게(`**`) 외 다른 마크업 금지.
3. 병합 + 검사:
   ```
   python work/concept-drafts/apply.py            # entries/ 전부
   python work/concept-drafts/apply.py speaking-process-listening   # 파일 stem만 골라서
   ```
   apply.py는 항목을 병합하고 `scripts/check_concepts.py`를 자동 실행한다.
4. 검사기 규칙: `sections` 3개 이상, 본문 공백 제외 400자 이상, `confused_with` id 존재, 근거 쪽이 DB에 존재. 별칭 겹침은 "(참고)"로만 표시되지만 되도록 없앤다.
5. 마무리: `python -m unittest discover -s tests`, `node --check dist/app.js`, 파일의 `note`와 README 55–57행의 항목 수 갱신, 커밋·푸시.

## 새 노트북에서 준비할 것

- `data/library.sqlite3`는 git에 없다. 복사해 오거나 `python scripts/rebuild_passages.py`로 다시 만들어야 `pages_for.py`와 검사기가 돈다.
- Python 3 + 프로젝트 의존성(`core.py`가 임포트되어야 함). `PYTHONIOENCODING=utf-8`로 실행.
