import sys,os
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import haversine,exact_tsp,nearest_neighbor_tsp
def test_same_point(): assert haversine((4.8,7.0),(4.8,7.0))==0
def test_exact():
 p=[(4.8,7),(4.81,7.01),(4.82,7),(4.81,6.99)];o,d=exact_tsp(p);assert o[0]==0 and o[-1]==0 and len(o)==5 and d>0
def test_nearest():
 p=[(4.8,7),(4.81,7.01),(4.82,7)];o,d=nearest_neighbor_tsp(p);assert o[0]==0 and o[-1]==0 and d>0
