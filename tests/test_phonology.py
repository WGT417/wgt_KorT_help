import unittest
from phonology import changes,pairs,change_names

class SoundChangeTests(unittest.TestCase):
    """The change a question's example shows, read off its spelling and pronunciation."""
    def test_standard_examples(self):
        for spelling,said,names in [
            ('국물','궁물',['비음화']),('밥물','밤물',['비음화']),('닫는','단는',['비음화']),('침략','침냑',['비음화']),
            ('부엌문','부엉문',['비음화','음절의 끝소리 규칙']),('읽는','잉는',['비음화','자음군 단순화']),
            ('신라','실라',['유음화']),('칼날','칼랄',['유음화']),
            ('같이','가치',['구개음화']),('굳히다','구치다',['구개음화','거센소리되기']),
            ('솜이불','솜니불',['ㄴ 첨가']),('물약','물략',['ㄴ 첨가','유음화']),('꽃잎','꼰닙',['ㄴ 첨가','비음화','음절의 끝소리 규칙']),
            ('국밥','국빱',['된소리되기']),('좋고','조코',['거센소리되기']),('축하','추카',['거센소리되기']),
            ('놓아','노아',['ㅎ 탈락']),('닭','닥',['자음군 단순화']),('앉다','안따',['된소리되기','자음군 단순화']),
            ('부엌','부억',['음절의 끝소리 규칙']),('피어','피여',['반모음 첨가'])]:
            self.assertEqual(changes(spelling,said),names,spelling)
    def test_no_name_where_nothing_changes_or_the_words_differ(self):
        # 연음 is no change; [보기] after 다음 is not a pronunciation; lengths that differ are left to the books.
        for spelling,said in [('국어','구거'),('다음','보기'),('보아','봐'),('국물','국물')]:
            self.assertEqual(changes(spelling,said),[],spelling)
    def test_examples_are_read_out_of_the_question(self):
        self.assertEqual(pairs("'국물'이 [궁물]로 발음되는 이유를 설명해 줘"),[('국물','궁물')])
        self.assertEqual(pairs('국물이 [궁물]로 나는 이유'),[('국물','궁물')])
        self.assertEqual(pairs("'국물'을 '궁물'로 발음하는 까닭"),[('국물','궁물')])
        self.assertEqual(change_names("'솜이불'을 [솜니불]로 발음하는 것은 어떤 음운 변동인가?"),['ㄴ 첨가'])
        self.assertEqual(change_names('다음 [보기]에서 고르시오'),[])
        self.assertEqual(change_names('비음화란 무엇인가?'),[])

class ExamplePageTests(unittest.TestCase):
    def test_pages_printing_the_example_with_its_pronunciation(self):
        import core
        from explanation import example_pages
        def where(q,category):
            ids=example_pages(q,category)
            with core.connect() as db:
                return {(r[0],r[1]) for r in db.execute('SELECT b.title,p.printed_page FROM pages p JOIN books b ON b.id=p.book_id WHERE p.id IN (%s)'%','.join(map(str,ids)))} if ids else set()
        self.assertEqual(where("'국물'이 [궁물]로 발음되는 이유","문법"),{('국어음운론 강의',293),('한국어문법총론 1',89)})
        # 같이 and 가치 side by side in a novel's commentary are not the example.
        self.assertEqual(where("'같이'가 [가치]로 발음되는 이유","전체"),{('한국어문법총론 1',75)})

if __name__=='__main__':unittest.main()
