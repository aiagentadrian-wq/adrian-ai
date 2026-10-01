import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import system_control as m
class Controls(unittest.TestCase):
 def test_pid_reuse_does_not_stop_other_process(self):
  record={'pid':7,'created':1,'exe':'python.exe'}
  with patch.object(m,'process_identity',return_value={**record,'created':2}),patch.object(m.subprocess,'run') as kill:
   m.Controller.__new__(m.Controller).terminate(record);kill.assert_not_called()
 def test_start_when_online_never_duplicates(self):
  with patch.object(m,'online',return_value=True),patch.object(m,'read_state',return_value={}),patch.object(m.Controller,'launch') as launch:
   m.Controller.__new__(m.Controller)._start();launch.assert_not_called()
 def test_stop_leaves_unowned_processes(self):
  with patch.object(m,'read_state',return_value={}),patch.object(m,'online',return_value=False),patch.object(m,'write_state') as save,patch.object(m.Controller,'terminate') as kill:
   m.Controller.__new__(m.Controller)._stop();kill.assert_not_called();save.assert_called_once_with({})
 def test_server_gets_graceful_stop_and_ai_follows(self):
  with tempfile.TemporaryDirectory() as td:
   stop=Path(td)/'stop';state={'server':{'pid':1},'ai':{'pid':2}}
   with patch.object(m,'STOP',stop),patch.object(m,'read_state',return_value=state),patch.object(m,'alive',side_effect=[True,False,False,True]),patch.object(m,'write_state'),patch.object(m,'online',return_value=False),patch.object(m.Controller,'terminate') as kill:
    m.Controller.__new__(m.Controller)._stop();self.assertTrue(stop.exists());kill.assert_called_once_with(state['ai'])
if __name__=='__main__':unittest.main()
