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
    def test_reading_view_keeps_doubtful_sentences_flagged(self):
        from passage_text import suspect_segments
        segs=suspect_segments('소설의 시점은 화자의 위치에 따라 달라진다. 화자가 이 ψΙ 속에서 어떤 위치를 차지하는가를 구별하는 것이 중요하다.')
        self.assertEqual([s['suspect'] for s in segs],[False,True])
        self.assertIn('ψ',segs[1]['text'])
