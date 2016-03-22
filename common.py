# author:sursen
# INIConfig: read or write ini
# SysCmdExecute: command line executer
# CommonUtils:common tools
import os
import subprocess
import ConfigParser
from tarfile import TUREAD

class INIConfig(object):
    def __init__(self, path):
        if path is None:
            raise NameError('path is none!!!!')
            return
        self.path = path
        self.cf = ConfigParser.ConfigParser()
        self.cf.read(self.path)
        self.sign = False
        
    def get(self, field, key):
        result = ""
        try:
            result = self.cf.get(field, key)
        except:
            result = ""
        return result
   
    def set(self, field, key, value):
        try:
            self.cf.set(field, key, value)
        except:
            return False
        self.sign = True
        return True
    
    def remove_key(self, field, key):
        try:
            self.cf.remove_option(field, key)
        except:
            return False
        self.sign = True
        return True
    
    def get_options(self,field):
        return self.cf.options(field)
       
    def get_sections(self):
        return self.cf.sections()
    
    def create_seciton(self,name):
        self.cf.add_section(name)
        self.sign=True
    
    def remove_section(self,name):
        self.cf.remove_section(name)
        self.sign=True
       
    
    def op_execute(self):
        if self.sign == False:
            return True        
        try:
            self.cf.write(open(self.path, 'w'))
        except:
            return False
        return True

class SysCmdExecute(object):
    def __init__(self, path=None):
        self.outstr = ''
        self.rtcode = 1
        self.outerr = '' 

    def sys_cmd_exec(self, cmdstr):
        if cmdstr is None:
            return (self.outstr, self.rtcode)
        mchild = subprocess.Popen(cmdstr, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        self.rtcode = mchild.wait()
        (self.outstr, self.outerr) = mchild.communicate()          
        return (self.outstr, self.rtcode, self.outerr)
    
class DevManager(object):
    def __init__(self, path=None):
        self.path = path
        if self.path is None:
            self.path = '/dev'
    
    def check_dev_exist(self,devpath):
        fullpath=self.path + '/' + devpath
        if os.path.exists(fullpath):
            return True
        else:
            return False
            
    def get_dev_list(self):
        return os.listdir(self.path)
    
    def get_newdev_name(self, begin_dev_list, end_dev_list):
        if begin_dev_list is None or end_dev_list is None:
            return None
        for n in begin_dev_list:
            if n in end_dev_list:
                continue
            else:
                return n
            
    def get_all_devs_for_volume(self, key_str=None):
        devarr = []
        devs = os.listdir(self.path)
        if key_str is None:
            return devs
        for n in devs:
            if key_str in n:
                devarr.append(n)
        return devarr
            
    def get_devname_by_volumename(self,volume_name,key_str=None):
        if volume_name is None:
            return None
        devs = self.get_all_devs_for_volume(key_str)
        lnum = len(devs)
        if lnum == 0:
            return None
        sys_cmd = SysCmdExecute()
        cmdstr = 'find /dev -type l -print0 | xargs --null file | grep -e' + volume_name
        (out_str, r_code, _) = sys_cmd.sys_cmd_exec(cmdstr)
        if r_code > 0:
            return None
        for n in devs:
            zn = '../' + n
            if zn in out_str:
                return n
        return None
                
class CommonUtils(object):
    def __init__(self):
        pass
    
    def get_next_char(self, sub_str='', all_str=''):
        if sub_str == '' or all_str == '':
            return None
        index = all_str.find(sub_str)
        if index < 0:
            return None
        slen = len(sub_str)
        return all_str[index + slen]
    
    def get_sizesign_from_str(self, f_str):
        if f_str is None:
            return f_str
        if 'G' in f_str:
            return 'G'
        if 'T' in f_str:
            return 'T'
        if 'M' in f_str:
            return 'M'
    
    def format_size(self, floatstr, signstr, basesign):
        if floatstr is None or signstr is None:
            return floatstr
        if basesign == 'G':
            if signstr == 'M':
                tmpnum = float(floatstr) / 1024
                return ('%.2f' % tmpnum)
            if signstr == 'G':
                return floatstr
            if signstr == 'T':
                tmpnum = float(floatstr) * 1000
                return ('%.2f' % tmpnum)
            
        if basesign == 'M':
            if signstr == 'G':
                tmpnum = float(floatstr) * 1000
                return ('%.2f' % tmpnum)
            if signstr == 'M':
                return floatstr
            if signstr == 'T':
                tmpnum = float(floatstr) * 1000 * 1000
                return ('%.2f' % tmpnum)
            
        if basesign == 'T':
            if signstr == 'G':
                tmpnum = float(floatstr) / 1024
                return ('%.2f' % tmpnum)
            if signstr == 'T':
                return floatstr
            if signstr == 'M':
                tmpnum = float(floatstr) / 1024 / 1024
                return ('%.2f' % tmpnum)       
              
        return floatstr        
            
    def get_float_from_str(self, cstr=None):
        if cstr is None:
            return None
        def f(x):
            if str(x).isdigit() or str(x) == ".":
                return x
            return
        return filter(f, cstr)
    
    def create_cinder_file(self,m_execute,m_r_helper,file_path):
        if os.path.exists(file_path):
            return
        cmdstr=['touch',file_path]
        m_execute(*cmdstr, root_helper=m_r_helper, run_as_root=True)
        anum=0
        while 1:
            if os.path.exists(file_path) or anum >5000:
                cmdstr=['chown','cinder:cinder',file_path]
                m_execute(*cmdstr, root_helper=m_r_helper, run_as_root=True)
                break
            else:
                anum=anum + 1
                continue
                        
        
        
                
        
