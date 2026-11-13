"""Import/exercise the EXTRACTED .deb; model and web replies are test fixtures."""
from pathlib import Path
import sys, json, tempfile, threading, os
from unittest.mock import Mock, patch
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'usr/share/auralyn-terminal'))
from auralyn_terminal import __version__
from auralyn_terminal.local_ai import OllamaClient
from auralyn_terminal.capabilities import CapabilityReader
from auralyn_terminal.web_sources import WebSource, WebBatch
from auralyn_terminal.web_command_ai import WebCommandResearch
from auralyn_terminal.install_advice import PackageReader
from auralyn_terminal.smart_search import SearchEngine
from auralyn_terminal.smart_catalog import ENTRIES,get_action
assert __version__=='1.0.0',__version__
assert len(ENTRIES)==99
assert sum(get_action(i) is not None for i in ENTRIES)==31
q='Wie sehe ich mein nvidia grafikkarten treiber?'
plan={'scope':'terminal','goal':'NVIDIA driver version Linux command','question':'',
      'tools':[{'command':'nvidia-smi','manual':'nvidia-smi(1)'}]}
choice={'scope':'terminal','goal':'Treiber anzeigen','question':'',
        'tools':[{'command':'nvidia-smi','manual':'nvidia-smi(1)','source_ids':['W1']}]}
answer={'status':'answer','title':'Treiber anzeigen','explanation':'Zeigt die NVIDIA-Informationen an.',
        'command':'nvidia-smi --query-gpu=driver_version --format=csv,noheader',
        'used_tools':['nvidia-smi(1)','grep'], 'manual_refs':['nvidia-smi(1)'],
        'follow_up':'','warning':'','source_ids':['W1']}
source=WebSource('W1','NVIDIA manual','https://docs.nvidia.com/deploy/nvidia-smi/index.html',
                 'nvidia-smi monitors NVIDIA GPUs and shows the driver version. Synthetic test excerpt.')
def reply(data):return {'done':True,'message':{'role':'assistant','content':json.dumps(data)}}
with tempfile.TemporaryDirectory() as temp:
    base=Path(temp);marker=base/'MUST_NOT_RUN';binary=base/'nvidia-smi'
    binary.write_text('#!/bin/sh\ntouch '+str(marker)+'\n');binary.chmod(0o755)
    c=OllamaClient();c.request=Mock(side_effect=[
        {'models':[{'name':'test:small','size':2000000,'details':{'format':'gguf'}}]},
        {'capabilities':['completion'],'model_info':{'general.architecture':'qwen3'}},
        reply(plan),reply(choice),reply(answer)])
    reader=CapabilityReader([base/'manuals'])
    web=Mock();web.search.return_value=WebBatch('driver version',(source,))
    packages=PackageReader(run=Mock())
    research=WebCommandResearch(c,reader,web,packages,{'id':'ubuntu','version':'26.04','codename':'resolute'})
    with patch.dict(os.environ,{'PATH':str(base)}):
        a=SearchEngine(client=c,capabilities=reader,web_research=research).answer(q,True,'test:small',web_enabled=True)
    assert a.command=='nvidia-smi --query-gpu=driver_version --format=csv,noheader',a
    assert a.entry_id=='gpu.driver_version',a
    assert 'grep:' not in a.evidence,a
    assert a.executable,a
    assert not a.install_command,a
    assert 'Web + Lokal' in a.source,a
    assert '1/2 Web' in a.evidence and '2/2 Lokal' in a.evidence,a
    assert 'kein lokales Handbuch' in a.evidence,a
    assert not marker.exists(),'Discovered executable must not run during a search'
    assert c.request.call_count==5
    print('Extracted package version:',__version__)
    print('Entries/actions:',len(ENTRIES),sum(get_action(i) is not None for i in ENTRIES))
    print('Exact screenshot question:',q)
    print('Fixture answer:',a.command)
    print('Source:',a.source)
    print('Actual local evidence:',a.evidence)
    print('Execute permission after future click:',a.executable)
    print('Target program executed during search:',marker.exists())
    print('Model HTTP requests (mock):',[call.args[0] for call in c.request.call_args_list])
    print('No live model/public web/GUI/install or target execution tested here.')
