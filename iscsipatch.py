import os
from cinder.volume.drivers.sursen import common
from cinder.openstack.common import log as logging
LOG = logging.getLogger(__name__)

class InitiatorManager(object):
    def __init__(self,initpath,iexecute,i_helper):
        if initpath is None or iexecute is None or i_helper is None:
            raise NameError('InitiatorManager init error')
        if os.path.exists(initpath):
            pass
        else:
            icomm=common.CommonUtils()
            icomm.create_cinder_file(iexecute, i_helper, initpath)

        self.inicfg=common.INIConfig(initpath)
        if len(self.inicfg.get_sections())==0:
            self.inicfg.create_seciton('ISCSIDEFAULT')
            self.inicfg.create_seciton('INITNAMELIST')
            self.inicfg.op_execute()
    
    def add_vol_initname_pair(self,volumename,initname):
        self.inicfg.set('INITNAMELIST',volumename,initname)
        self.inicfg.op_execute()
    
    def remove_vol_initname_pair(self,volumename):
        self.inicfg.remove_key('INITNAMELIST',volumename)
        self.inicfg.op_execute()
    
    def get_vol_initname(self,volumename):
        return self.inicfg.get('INITNAMELIST', volumename)
        
        
        
