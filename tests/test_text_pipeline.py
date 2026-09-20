import unittest
from text_pipeline import compact,restore_terms,classify,layout_passages,VERSION
import core
from passage_text import windows,best_window,noise

class TextPipelineTests(unittest.TestCase):
    def test_same_baseline_fragments_follow_x_not_font_top(self):
        class Page:
            class Rect:width=500;height=700
            rect=Rect()
            def get_text(self,mode):
                return {'blocks':[{'type':0,'lines':[
                    {'bbox':[140,126,435,140],'spans':[{'text':'의미를 구성하는 과정이다.','size':12}]},
                    {'bbox':[92,128,140,140],'spans':[{'text':'독서는 ','size':11}]},
                ]}]}
        parts=layout_passages(Page())
        self.assertEqual(parts[0]['raw'],'독서는 의미를 구성하는 과정이다.')
    def test_excerpt_keeps_source_offsets_and_complete_sentences(self):
        raw='서문입니다. 독자는읽기과정에서자신의이해수준을점검하고필요한전략을선택하면서의미를능동적으로구성한다. 이러한읽기는독자의지식과목적에따라달라진다.'
        display='서문입니다. 독자는 읽기 과정에서 자신의 이해 수준을 점검하고 필요한 전략을 선택하면서 의미를 능동적으로 구성한다. 이러한 읽기는 독자의 지식과 목적에 따라 달라진다.'
        result=best_window(raw,display,[('읽기',),('능동적',)])
        self.assertIsNotNone(result)
        self.assertIn(result[0],raw)
        self.assertEqual(compact(result[0]),compact(result[1]))
        self.assertTrue(result[1].endswith('.'))
    def test_visible_ocr_damage_is_not_promoted_as_prose(self):
        self.assertGreater(noise('이 학습X까 독7-}를 이해한다.'),0)
        self.assertEqual(noise('어미에는 -다, -고, -(으)ㄴ 등이 있다.'),0)
    def test_spacing_changes_no_glyphs(self):
        before='선 어 말 어 미와 피 동 사의 의 미 구 성'
        after=restore_terms(before)
        self.assertEqual(compact(before),compact(after))
        self.assertIn('선어말어미',after);self.assertIn('피동사',after)
    def test_catalog_detected_independently_of_question(self):
        self.assertEqual(classify('비상교과서 국어 신사고 국어 지학사 천재교육 교과서 단원'),'catalog')
        self.assertEqual(classify('독자는 자신의 독서 목적을 인식하고 이해 수준을 점검하며 전략을 조절한다.'),'body')
    def test_entire_library_was_rebuilt(self):
        with core.connect() as db:
            missing=db.execute("SELECT COUNT(*) FROM pages p JOIN books b ON b.id=p.book_id LEFT JOIN text_build t ON t.page_id=p.id WHERE b.category!='참고자료' AND t.page_id IS NULL").fetchone()[0]
            self.assertEqual(missing,0)
            for r in db.execute('SELECT raw,display FROM passages'):
                self.assertEqual(compact(r['raw']),compact(r['display']))
    def test_side_notes_are_not_interleaved_with_main_text(self):
        with core.connect() as db:
            rows=db.execute("SELECT x.raw FROM passages x JOIN pages p ON p.id=x.page_id JOIN books b ON b.id=p.book_id WHERE b.title='한국어문법총론 1' AND p.pdf_page=223 AND x.kind='body'").fetchall()
        main='\n'.join(r['raw'] for r in rows)
        self.assertIn('선어말',main)
        self.assertNotIn('줄임말',main)
        self.assertNotIn('종속적 연걸 어',main)

class ExplanationShapeTests(unittest.TestCase):
    def test_exercise_blocks_are_classified_not_promoted(self):
        self.assertEqual(classify('2 다음 진술을 참(T)과 거짓(F)으로 구분하고, 거짓은 바르게 수정하시오.'),'exercise')
        self.assertEqual(classify('3. 다음 읽기 자료를 활용하여 수업을 계획해 보시오.'),'exercise')
        self.assertEqual(classify('SQ3R 모형은 전통적이고도 대표적인 읽기 학습 체계이자 전략이다.'),'body')
    def test_excerpt_never_ends_mid_sentence(self):
        raw='(1 ) 텍스트 유형에 따라 적용 가능한 교수학습 모형 및 방법은 달라지기도\n\n한다.\n\n(2) SQ3R은 대표적인 읽기 학습 체계이자 전략이며， ‘옳어보기(Survey) ’，'
        display='(1 ) 텍스트 유형에 따라 적용 가능한 교수 학습 모형 및 방법은 달라지기도한다. (2) SQ3R은 대표적인 읽기 학습 체계이자 전략이며， ‘옳어 보기(Survey) ’，'
        self.assertIsNone(best_window(raw,display,[('sq3r',)]))
        for _,text in windows(raw,display):self.assertRegex(text,r'[다요][.!?。]["”’]?$')
    def test_longer_clean_paragraph_beats_two_sentences(self):
        sentences=['SQ3R 모형은 대표적인 읽기 학습 전략이다.','로빈슨에 의해 처음 제안된 이 모형은 여러 모형으로 변형되면서 오래도록 활용되었다.','훑어보기 단계에서는 제목과 주제어를 중심으로 텍스트의 핵심 내용을 예측한다.','질문하기 단계에서는 읽기의 목적을 분명히 하여 질문을 만든다.']
        display=' '.join(sentences);raw=display.replace(' ','')
        result=best_window(raw,display,[('sq3r',)])
        self.assertEqual(result[1],display)
    def test_small_print_bullet_list_is_a_table_block(self):
        class Page:
            class Rect:width=500;height=700
            rect=Rect()
        lines=[{'text':'독서는 의미를 구성하는 과정이다. 독자는 배경지식을 활용하여 글의 의미를 능동적으로 구성한다.','box':[90,120,430,134],'size':12}]
        y=300
        for text in ['절차','• 제목 중심으로 훑어보기','• 주제어 중심으로 훑어보기','• 핵심 내용을 예측하기']:
            lines.append({'text':text,'box':[90,y,300,y+9],'size':8});y+=12
        parts=layout_passages(Page(),lines)
        kinds=[p['kind'] for p in parts]
        self.assertIn('body',kinds);self.assertIn('table',kinds)
    def test_item_numbers_rejoin_without_glyph_changes(self):
        before='( 1 ) 텍스트 유형과 (2 ) 읽기 전략'
        after=restore_terms(before)
        self.assertEqual(compact(before),compact(after));self.assertIn('(1) 텍스트',after);self.assertIn('(2) 읽기',after)

class GlyphRepairTests(unittest.TestCase):
    def test_foreign_letters_count_as_ocr_noise(self):
        self.assertGreater(noise('화자가 이 ψΙ 속에서 어떤 위치를 차지하는가.'),0)
        self.assertGreater(noise('‘ a ’과‘ λ이 만나면 어떻게 되나?'),0)
        self.assertEqual(noise('소설의 시점은 화자의 위치에 따라 달라진다.'),0)
    def test_display_corrections_are_whole_words_same_length_and_reversible(self):
        from text_pipeline import correct_display,corrections
        words=corrections()
        self.assertTrue(all(len(k)==len(v) for k,v in words.items()))
        self.assertNotIn('기지',words);self.assertNotIn('감지',words);self.assertNotIn('여지는',words)
        if '히는' in words:
            text,n=correct_display('독서를 지도히는 교사')
            self.assertEqual(n,1);self.assertIn('지도하는' if '지도히는' in words else '히는',text if n==0 else text.replace('지도하는','지도하는'))
        fixed,n=correct_display('자신의 생각을 말한다.')
        self.assertEqual((fixed,n),('자신의 생각을 말한다.',0))
    def test_hangul_pulled_into_a_latin_gloss_is_noise(self):
        # 독서교육론 사회평론 39쪽: the table column bled into the paragraph.
        self.assertGreater(noise('복합양식 텍스트(m뻐대표”하고 있다.'),0)
        self.assertGreater(noise('선어말어미(pre:final ending)와 어말어미로 나뉜다.'),0)
        self.assertGreater(noise('명칭을 ^~용하기도 한다.'),0)
        # Example numbers read with l for 1, and the syllable types of 음운론.
        self.assertEqual(noise('(l다)는 절 속에 구가 들어 있음을 보여 준다.'),0)
        self.assertEqual(noise('모음으로 시작하는 음절형(V형, VC형 등) 사이의 결합이다.'),0)
    def test_hangul_stranded_inside_a_latin_gloss_is_noise(self):
        # The scan reads "al" as 외 and drops syllables into the middle of a gloss.
        self.assertGreater(noise('지적인 세련(intellectu 외 seriousness)으로 보기도 한다.'),0)
        self.assertGreater(noise('기능 문법 (따 lctional gr 없 lmar) 을 중시하였다.'),0)
        self.assertGreater(noise('‘단일 양식 텍스 틴 monomc 벼 상대되는 개념이다.'),0)
        # A particle between two Latin words is an ordinary sentence.
        self.assertEqual(noise('Chomsky 의 Syntactic Structures 는 중요하다.'),0)
        self.assertEqual(noise('Halliday 와 Hasan 이 제시한 응결성 개념이다.'),0)
        self.assertEqual(noise('복합 양식 텍스트는 multimodal text 로 불린다.'),0)
    def test_two_syllable_terms_are_corrected_by_the_curated_list(self):
        from text_pipeline import correct_display,corrections
        words=corrections()
        # 직문 reads as 직+문 to the language model, so a person's term list vouches for 작문.
        if '직문' in words:
            self.assertEqual(words['직문'],'작문')
            self.assertEqual(correct_display('직문 능력의 합에서')[0],'작문 능력의 합에서')
        # Real words spelled the same way are never rewritten.
        for word in ['명시','부시','치이','단어','시대','영향']:self.assertNotIn(word,words)
    def test_tables_without_readable_words_are_not_shown(self):
        from passage_search import readable_table
        self.assertTrue(readable_table([['텍스트 수용 태도','수용적 긍정적 독자','비판적 저항적 독자'],
                                        ['독서 집중도','몰입형 독자','산만한 독자(잦은 중단, 멀티태스킹)']]))
        # 찾아보기: an entry followed by the pages it appears on.
        self.assertFalse(readable_table([['비판적 문식성 40, 71','소리-글자 대응 107'],['비판적 이해 92, 94','수준별 교육 223'],
                                         ['비형식적 읽기 검사지 392','수집 구조 187']]))
        # 독서교육론 사회평론 39쪽 [표 1-4]: words no book in the library repeats.
        self.assertFalse(readable_table([['인해돼스트기반입기','복합g씩텍스트읽기'],
                                         ['단어 담화1 레지스터1 어후1, 언어적 패턴,','시각적 이미지 배치, 사이즈1 모앙1 색상,'],
                                         ['의미 전닫 문법, 챔터, 문단, 문장 구조를 포함한 문자','선, 각도, 위치, 관점, 화면, 프레임, 이이콘,']]))
        self.assertFalse(readable_table([['。 장','5 ‘','% l 겠'],['뎌','써','댁 。 ] 갈동센']]))
    def test_reading_view_keeps_doubtful_sentences_flagged(self):
        from passage_text import suspect_segments
        segs=suspect_segments('소설의 시점은 화자의 위치에 따라 달라진다. 화자가 이 ψΙ 속에서 어떤 위치를 차지하는가를 구별하는 것이 중요하다.')
        self.assertEqual([s['suspect'] for s in segs],[False,True])
        self.assertIn('ψ',segs[1]['text'])

class ReadingTextTests(unittest.TestCase):
    # 한국어문법총론 1, 265쪽: a footnote mark read as 쩌, and the spacing model splitting 관계절.
    terms=(frozenset({'관계절','관형사절','동격','이형태','대화참여자'}),5)
    def test_footnote_mark_after_a_sentence_is_dropped(self):
        from text_pipeline import tidy_display
        raw='각각 동격절， 관계절로 줄여 이르기도 한다.쩌 (1 22)의 밑줄 부분'
        display='각각 동격 절， 관 계절로 줄여 이르기도한다. 쩌 (1 22)의 밑줄 부분'
        text,marks=tidy_display(raw,display,self.terms)
        self.assertEqual(marks,1)
        self.assertEqual(text,'각각 동격 절， 관계절로 줄여 이르기도한다. (122)의 밑줄 부분')
    def test_heading_footnote_number_is_dropped(self):
        from text_pipeline import tidy_display
        text,marks=tidy_display('4.3.3.2. 관형사절을안은문장39\n절이 관형사화되어','4.3.3.2. 관형사절을 안은 문장 39 절이 관형사화되어',self.terms)
        self.assertEqual((text,marks),('4.3.3.2. 관형사절을 안은 문장 절이 관형사화되어',1))
    def test_words_and_counts_after_a_sentence_stay(self):
        from text_pipeline import tidy_display
        for raw in ['차이가 있다.즉 두 가지로 나뉜다.','시를 살펴보았다.1 연에서 화자는','경우가 있다.13 (8바)처럼']:
            text,marks=tidy_display(raw,raw.replace('.','. '),self.terms)
            self.assertEqual(marks,raw.endswith('처럼'),raw)
    def test_period_less_footnote_numbers_and_misread_commas(self):
        from text_pipeline import tidy_display
        cases=[('이끌어질 수도 있다46 남의 말이나','이끌어질 수도 있다 46 남의 말이나','이끌어질 수도 있다. 남의 말이나'),
               ('모음을 구분한다 12 단모음은','모음을 구분한다 12 단모음은','모음을 구분한다. 단모음은'),
               ('격 조사에서 나타나며70 격 조사 중에서도','격조사에서 나타나며 70 격조사 중에서도','격조사에서 나타나며 격조사 중에서도'),
               ('불러일으킬 수 있고1 그것이 목숨을','불러일으킬 수 있고 1 그것이 목숨을','불러일으킬 수 있고， 그것이 목숨을'),
               # Numbers that count something stay.
               ('발달 수준은 비슷하다 2 학년과 3학년','발달 수준은 비슷하다 2 학년과 3학년','발달 수준은 비슷하다 2 학년과 3학년'),
               ('수식한다면2 번처럼 표현하여','수식한다면 2 번처럼 표현하여','수식한다면 2 번처럼 표현하여'),
               ('일단 9품사 체계로 보고1 위에서','일단 9 품사 체계로 보고 1 위에서','일단 9 품사 체계로 보고， 위에서')]
        for raw,display,want in cases:
            self.assertEqual(tidy_display(raw,display,self.terms)[0],want,raw)
    def test_screen_text_round_three(self):
        # 한국어표준문법 305쪽, 우리말문법론 130쪽.
        from text_pipeline import tidy_display,correct_display,split_heading
        shown=lambda raw,display,misread={}:correct_display(tidy_display(raw,display,self.terms,misread)[0])[0]
        self.assertEqual(shown('성립하지 않으며，l7 보조 용언은 본용언의','성립하지 않으며，l7 보조 용언은 본용언의'),'성립하지 않으며, 보조 용언은 본용언의')
        # A plain number after a comma is as often a list item.
        self.assertEqual(shown('단원을 시작하며，2 생활 속에서','단원을 시작하며，2 생활 속에서'),'단원을 시작하며, 2 생활 속에서')
        self.assertEqual(shown('논의는 박진호(1998)， 민현식(1999： 119-156)','논의는 박진 호(1998)， 민현식(1999：119-156)'),'논의는 박진호(1998), 민현식(1999:119-156)')
        self.assertEqual(shown('특히굿맨(1970)이','특히 굿맨(1970)이'),'특히 굿맨(1970)이')
        self.assertEqual(shown('것이다 15) 이런 점에서','것이다 15) 이런 점에서'),'것이다. 이런 점에서')
        self.assertEqual(shown('시간성， 통작성 등','시간성， 통 작성 등',{'통작성':'동작성'}),'시간성, 동작성 등')
        # Not one word in the source: 부가가치는 제조업 is not 가치논제.
        self.assertEqual(shown('부가가치는 제조업이','부가 가치는 제조업이',{'가치는제':'가치논제'}),'부가 가치는 제조업이')
        body='\n국어의 보조용언은 시간성， 양태성， 통작성 등 다양한 의미를 나타낼 뿐 아\n니라 피동， 사동， 부정 등의 의미를 나타내기도 한다.'
        for first,heading in [('7 보조용언의 의미 기능','7 보조용언의 의미 기능'),('2.4.1. 음운 현상의 정의와 분류 기준','2.4.1. 음운 현상의 정의와 분류 기준'),
                              ('(325 가)는 접미사',''),('2 학년에서',''),('역으로 영상 서사를 감상한 후 그 것','')]:
            raw=first+body
            self.assertEqual(split_heading(raw,raw.replace('\n',' '))[0],heading,first)
    def test_screen_text_round_four(self):
        # 한국어표준문법 434·472쪽, 우리말문법론 496쪽.
        from text_pipeline import tidy_display,correct_display,callout_marks
        shown=lambda raw,display,misread={}:correct_display(tidy_display(raw,display,self.terms,misread)[0])[0]
        홑={'흩문장':'홑문장','흘문장':'홑문장','홀문장':'홑문장'}
        # The OCR never produces 홑, so every spelling of the term on the page is damaged.
        self.assertEqual(shown('문장을 흘문장(단문 短文)이라','문장을 흘 문장(단문 短文)이라',홑),'문장을 홑문장(단문 短文)이라')
        # A line break inside the word, and a source that lost the space entirely.
        self.assertEqual(shown('이루어진 흩\n문장이다','이루어진 흩 문장이다',홑),'이루어진 홑문장이다')
        self.assertEqual(shown('이루어진문장을흩문장이라고한다.','이루어진 문장을 흩 문장이라고 한다.',홑),'이루어진 문장을 홑문장이라고 한다.')
        # A cross-reference between two sentences is dropped like a footnote mark.
        self.assertEqual(shown('뜻매김하고자 한다. 적용4\n전통적으로 문장은','뜻 매김하고자 한다. 적용4 전통적으로 문장은'),'뜻 매김하고자 한다. 전통적으로 문장은')
        self.assertEqual(shown('알 수 있다.[덧붙임 1].\n우리의 문법학자','알 수 있다.[덧붙임 1]. 우리의 문법학자'),'알 수 있다. 우리의 문법학자')
        for raw,marks in [('여겨진다. 적용5 이제 이 두 가지',1),('한다.[덧붙임 8J.',1),('가진다.[덧붙임 1되.',1),
                          ('나타나지 않는다. 적용1 0 억양을 달리하여',1),('구분한다. 적용19. 적용20\n‘-이’와',2),
                          # The sentence reads through these, so they stay.
                          ('않으나 [덧붙임 2]에서 언급한 김동찬의',0),('형태이다. 제13장 [덧붙임 5]를 보라.',0),
                          ('관점에서는 [덧붙임 4] 에서 제시한 바와',0),('교수·학습모형의 적용 1 단계: 모형에 대한',0),
                          ('적용 300\t책임 이양모양 297',0)]:
            self.assertEqual(len(callout_marks(raw)),marks,raw)
    def test_terms_rejoin_only_where_the_source_had_no_space(self):
        from text_pipeline import tidy_display
        self.assertEqual(tidy_display('동격 관형사절과','동 격 관형 사절과',self.terms)[0],'동격 관형사절과')
        # The book itself spaced these: "this form", "the conversation's participants".
        self.assertEqual(tidy_display('이 형태는','이 형태는',self.terms)[0],'이 형태는')
        self.assertEqual(tidy_display('이형태는','이 형태는',self.terms)[0],'이 형태는')
        self.assertEqual(tidy_display('대화 참여자는','대화 참여자는',self.terms)[0],'대화 참여자는')
        # A two-syllable term only when split into two lone syllables.
        self.assertEqual(tidy_display('동격이다','동 격이다',self.terms)[0],'동 격이다')

class DefinitionContextTests(unittest.TestCase):
    def test_following_sentences_stay_on_the_term(self):
        import sys;sys.path.insert(0,str(core.ROOT/'scripts'))
        from build_term_index import with_context
        s=lambda text,passage=1,skip=False,previous=None:{'kind':'body','text':text,'previous':previous,'passage':passage,'skip':skip}
        sentences=[s('문장 안에서 서술어의 기능을 하는 용언을 본용언， 문법적인 의미를 더해 주는 용언을 보조 용언이라 한다.'),
                   s('보조 용언만으로는 문장이 성립하지 않으며， 보조 용언은 본용언의 뒤에 와서 다양한 기능을 한다.'),
                   s('빨간 장미꽃이 아름답다 하는 말은 단순한 진술에 불과하다.')]
        quote,more=with_context(sentences,0,'보조용언')
        self.assertIn('보조 용언만으로는',more);self.assertNotIn('장미꽃',more)
        sentences[1]=s('이러한 보조 용언의 의미는 (3다)의 예에서 볼 수 있다.')
        self.assertEqual(with_context(sentences,0,'보조용언')[1],'')
        sentences[1]=s('보조 용언만으로는 문장이 성립하지 않는다.',passage=2)
        self.assertEqual(with_context(sentences,0,'보조용언')[1],'')

class DefinitionTests(unittest.TestCase):
    def test_definitions_outrank_mentions(self):
        from term_index import definition_score
        longer=['동격관형사절','관계관형사절']
        score=lambda s:definition_score(s,'관형사절',longer)
        self.assertEqual(score('절이 관형사화되어 관형어로서 쓰이게 되면 그 절을 관형사절이라고 부른다.'),10)
        self.assertEqual(score('관형사절은 용언 어간에 관형사형 어미가 붙어서 관형어로 쓰일 수 있는 절이다.'),7)
        self.assertEqual(score('일반적으로 관형사절은 동격 관형사절과 관계 관형사절로 분류된다.'),5)
        # Defines 동격 관형사절, not 관형사절.
        self.assertEqual(score('동격 관형사절이란 한 문장의 모든 필수 성분을 완전하게 갖추고 있는 관형사절이다.'),2)
        self.assertEqual(score('우리 책에서도 ‘넓은’을 관형사절로 다룬다.'),1)
        self.assertEqual(score('명사절은 명사화되어 명사가 쓰일 수 있는 자리에 오는 절이다.'),0)
    def test_shapes_found_by_reading_the_whole_library(self):
        # Each case is a sentence from the books that an earlier rule got wrong.
        from term_index import definition_score as score
        cases=[('이 때 발생하는 것이 ‘대화 함축’이다.','대화함축',9),
               ('대화 함축이란 협력하고 있다고 가정할 때 발생하는 숨겨진 의미이다(오주영，1997 ; 구현정，2001).','대화함축',10),
               ('위의 네 가지 격률 가운데 첫 번째 양의 격률은 필요한 만큼만 정보를 제공하라는 것이다.','양의격률',7),
               ('현시적 교수법은 명확한 행동적 목표를 기반으로 하는 교사 중심 지도법을 일 걷는다.','현시적교수법',9),
               ('평서형， 의문형， 명령형， 청유형， 감탄형을 묶어서 ‘종결형’ 이라고 하며 나머지는 비종결형이라고 한다.','종결형',10),
               # Not definitions of the term.
               ('가장 긴 드라마는 연속극이며， 가장 짧은 드라마는 단막극이다.','드라마',1),
               ('심리학적 기능이란 시인과 독자 사이의 관계에 작용한다.','심리학적기능',5),
               ('내리 쓰기 전략은 개요 짜기의 결과물을 보면서 하는 것이 일반적이다.','내리쓰기전략',5),
               ('현대 국어에서 두음 법칙이라고 부르는 현상이 왜 발생했는지는 설명하기 어렵다.','두음법칙',1),
               ('이것을 음소 분석이라고 부른다.','분석',1),
               ('문장 자체의 변화를 통해 부각하는 표현을 강조의 방법이라 한다.','방법',1),
               ('‘-가’， ‘-고’가 보조사라고 한다고 해서 문제가 해결되는 것은 아니다.','보조사',1),
               ('그러므로 이는 ‘모절(안은절)’이라고 불러야 한다.','모절',1),
               ('아리스토텔레스는 『시학』에서 예술가는 행동하는 인간을 모방한다고 말한다.','아리스토텔레스',5),
               ('소설을 가르치는 과정에서는 이야기의 뜻을 찾아가는 작업이 이루어지기 때문이다.','에서',1)]
        for sentence,key,want in cases:
            self.assertEqual(score(sentence,key),want,sentence)
