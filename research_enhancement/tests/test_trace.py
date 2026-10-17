import unittest
from research_enhancement.deterministic_trace import create
class TestTrace(unittest.TestCase):
 def test_repeatability(self):
  rows=[{'features':[i],'expected':i} for i in range(8)]
  self.assertEqual(create(rows,25,42),create(rows,25,42))
  self.assertEqual(set(x['row_index'] for x in create(rows,25,42)),set(range(8)))
if __name__=='__main__':unittest.main()
