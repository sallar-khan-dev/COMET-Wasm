import unittest
from research_enhancement.scheduler_v2 import decide,interpolate,UnsupportedOperatingPoint

def example():
    def p(mem,p95):return {'memory_by_tenant':{1:mem,20:mem+20},'p95_by_tenant_and_rate':{1:{100:p95,200:p95+1},20:{100:p95+1,200:p95+2}},'capacity_by_tenant_and_rate':{1:{100:300,200:300},20:{100:300,200:300}}}
    return {'demo':{'wasmtime':p(40,3),'docker':p(20,4)}}
class TestPolicy(unittest.TestCase):
    def test_docker_when_feasible_and_lower_memory(self):self.assertEqual(decide(example(),'demo',100,1,100,10)['backend'],'docker')
    def test_rejection(self):self.assertFalse(decide(example(),'demo',100,1,10,2)['admitted'])
    def test_no_extrapolation(self):
        with self.assertRaises(UnsupportedOperatingPoint):interpolate({1:2,20:4},21)
    def test_unsupported_does_not_admit(self):self.assertFalse(decide(example(),'demo',400,1,100,10)['admitted'])
if __name__=='__main__':unittest.main()
