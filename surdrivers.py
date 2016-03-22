import socket
from cinder import utils
from oslo.config import cfg
from cinder import exception
from cinder.volume import driver
from cinder.brick.iscsi import iscsi
from cinder.volume import utils as cutils
from cinder.volume.drivers import remotefs
from cinder.brick import exception as iexception
from cinder.openstack.common import log as logging
from cinder.volume.drivers.sursen import iscsipatch
from cinder.openstack.common import processutils as putils


LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.IntOpt('num_shell_tries',
               default=3,
               help='Number of times to attempt to run flakey shell commands'),
    cfg.IntOpt('reserved_percentage',
               default=0,
               help='The percentage of backend capacity is reserved'),
    cfg.IntOpt('iscsi_num_targets',
               default=100,
               help='The maximum number of iSCSI target IDs per host'),
    cfg.StrOpt('iscsi_target_prefix',
               default='iqn.2010-10.org.openstack:',
               help='Prefix for iSCSI volumes'),
    cfg.StrOpt('iscsi_ip_address',
               default='$my_ip',
               help='The IP address that the iSCSI daemon is listening on'),
    cfg.StrOpt('initiator_path',
               default='/etc/cinder/initiatortable.ini',
               help='The record for host initiatorname'),
    cfg.IntOpt('iscsi_port',
               default=3260,
               help='The port that the iSCSI daemon is listening on'),
    cfg.IntOpt('num_volume_device_scan_tries',
               deprecated_name='num_iscsi_scan_tries',
               default=3,
               help='The maximum number of times to rescan targets'
                    ' to find volume'),
    cfg.StrOpt('volume_backend_name',
               default=None,
               help='The backend name for a given driver implementation'),
    cfg.StrOpt('volume_pool_name',
               default=None,
               help='The pool name'),
    cfg.BoolOpt('use_multipath_for_image_xfer',
                default=False,
                help='Do we attach/detach volumes in cinder using multipath '
                     'for volume to image and image to volume transfers?'),
    cfg.StrOpt('volume_clear',
               default='zero',
               help='Method used to wipe old volumes (valid options are: '
                    'none, zero, shred)'),
    cfg.IntOpt('volume_clear_size',
               default=0,
               help='Size in MiB to wipe at start of old volumes. 0 => all'),
    cfg.StrOpt('volume_clear_ionice',
               default=None,
               help='The flag to pass to ionice to alter the i/o priority '
                    'of the process used to zero a volume after deletion, '
                    'for example "-c3" for idle only priority.'),
    cfg.StrOpt('iscsi_helper',
               default='tgtadm',
               help='iSCSI target user-land tool to use. tgtadm is default, '
                    'use lioadm for LIO iSCSI support, iseradm for the ISER '
                    'protocol, or fake for testing.'),
    cfg.StrOpt('volumes_dir',
               default='$state_path/volumes',
               help='Volume configuration file storage '
               'directory'),
    cfg.StrOpt('iet_conf',
               default='/etc/iet/ietd.conf',
               help='IET configuration file'),
    cfg.StrOpt('lio_initiator_iqns',
               default='',
               help=('Comma-separated list of initiator IQNs '
                     'allowed to connect to the '
                     'iSCSI target. (From Nova compute nodes.)')),
    cfg.StrOpt('iscsi_iotype',
               default='fileio',
               help=('Sets the behavior of the iSCSI target '
                     'to either perform blockio or fileio '
                     'optionally, auto can be set and Cinder '
                     'will autodetect type of backing device')),
    cfg.StrOpt('volume_dd_blocksize',
               default='1M',
               help='The default block size used when copying/clearing '
                    'volumes'),
    cfg.StrOpt('volume_copy_blkio_cgroup_name',
               default='cinder-volume-copy',
               help='The blkio cgroup name to be used to limit bandwidth '
                    'of volume copy'),
    cfg.IntOpt('volume_copy_bps_limit',
               default=0,
               help='The upper limit of bandwidth of volume copy. '
                    '0 => unlimited'),
    cfg.StrOpt('iscsi_write_cache',
               default='on',
               help='Sets the behavior of the iSCSI target to either '
                    'perform write-back(on) or write-through(off). '
                    'This parameter is valid if iscsi_helper is set '
                    'to tgtadm or iseradm.'),
    cfg.StrOpt('driver_client_cert_key',
               default=None,
               help='The path to the client certificate key for verification, '
                    'if the driver supports it.'),
    cfg.StrOpt('driver_client_cert',
               default=None,
               help='The path to the client certificate for verification, '
                    'if the driver supports it.'),
    cfg.IntOpt('check_times_where_resume',
               default=3,
               help='only for migration when instance is suspended or shut off'),
    cfg.IntOpt('disk_copy_speed',
               default=40,
               help='disk copy speed'),

]

CONF = cfg.CONF
CONF.register_opts(volume_opts)

class SurIscsiVolumeDriver(driver.VolumeDriver):
    def __init__(self, *args, **kwargs):
        super(SurIscsiVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        self._execute = utils.execute
        self.r_helper = utils.get_root_helper()
        
        self.hostname = socket.gethostname()
        
        self.iscsiobj = driver.ISCSIDriver(*args, **kwargs)
        self.target_helper = self.iscsiobj.get_target_helper(self.db)
        self.targetbase = iscsi.LioAdm(root_helper=self.r_helper,
                              execute=self._execute)     
        
        self.volume_dd_bksize = self.configuration.safe_get('volume_dd_blocksize')
        self.initiator_path=self.configuration.safe_get('initiator_path')       
        if self.volume_dd_bksize.isdigit() is False:
            self.volume_dd_bksize = '1M'
        else:
            if int(self.volume_dd_bksize) > 1000 or int(self.volume_dd_bksize) < 1024:
                self.volume_dd_bksize = '1M'
            else:
                self.volume_dd_bksize = int(self.volume_dd_bksize) * 1024
                
        self.initiator_manager=iscsipatch.InitiatorManager(self.initiator_path,self._execute,self.r_helper)
                
        self._stats = {}

    def set_execute(self, execute):
        self._execute = execute
        return
    
    def _sizestr(self, size_in_g):
        if int(size_in_g) == 0:
            return '100Mb'
        return '%sGb' % size_in_g
    
    def _escape_snapshot(self, snapshot_name):
        # Linux ZFS reserves name that starts with snapshot, so that
        # such volume name can't be created. Mangle it.
        if '@' in snapshot_name:
            raise NameError('wrong snapshot name')
        return snapshot_name

    def _get_iscsitarget_chap_auth(self, context, iscsi_name):
        try: 
            # 'iscsi_name': 'iqn.2010-10.org.openstack:volume-00000001' 
            vol_id = iscsi_name.split(':volume-')[1] 
            volume_info = self.db.volume_get(context, vol_id) 
            # 'provider_auth': 'CHAP user_id password' 
            if volume_info['provider_auth']: 
                return tuple(volume_info['provider_auth'].split(' ', 3)[1:]) 
        except exception.NotFound: 
            LOG.debug('Failed to get CHAP auth from DB for %s', vol_id) 

    def _create_export(self, context, volume):
        """Creates an export for a logical volume.""" 
        if volume['name'] is None:
            return None

        volume_path = self._get_volume_devpath(volume['name'])
        
        conf = self.configuration
        iscsi_name = "%s%s" % (conf.iscsi_target_prefix,
                               volume['name'])
        max_targets = conf.safe_get('iscsi_num_targets')
        (iscsi_target, lun) = self.target_helper._get_target_and_lun(context,
                                                       volume,
                                                       max_targets)
        try:
            current_chap_auth = self.target_helper._get_target_chap_auth(context, iscsi_name)
        except:
            current_chap_auth = self._get_iscsitarget_chap_auth(context, iscsi_name)
            pass
                      
        if current_chap_auth:
            (chap_username, chap_password) = current_chap_auth
        else:
            chap_username = cutils.generate_username()
            chap_password = cutils.generate_password()
        chap_auth = self.target_helper._iscsi_authentication('IncomingUser',
                                               chap_username,
                                               chap_password)
        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        
        tid = self.targetbase.create_iscsi_target(iscsi_name, iscsi_target, 0,
                                       volume_path,
                                       chap_auth,
                                       write_cache=conf.iscsi_write_cache)
        data = {}
        data['location'] = self.target_helper._iscsi_location(
            conf.iscsi_ip_address, tid, iscsi_name, conf.iscsi_port, lun)
        data['auth'] = self.target_helper._iscsi_authentication(
            'CHAP', chap_username, chap_password)

        return {
            'provider_location': data['location'],
            'provider_auth': data['auth'],
        }
       
    def remove_export(self, context, volume):
        # self.target_helper.remove_export(context, volume)
        try:
            iscsi_target = self.db.volume_get_iscsi_target_num(context, volume['id'])
        except exception.NotFound:
            LOG.info("Skipping remove_export. No iscsi_target, provisioned for volume: %s" % volume['id'])
            return

        self.targetbase.remove_iscsi_target(iscsi_target, 0, volume['id'], volume['name'])
        try:
            self.initiator_manager.remove_vol_initname_pair(volume['id'])
        except:
            LOG.warn('Failed to remove initiator for the volume %s' &volume['name'])
        
    def validate_connector(self, connector):
        self.iscsiobj.validate_connector(connector)
        
    def initialize_connection(self, volume, connector):
        if CONF.iscsi_helper == 'lioadm':
            # self.target_helper.initialize_connection(volume, connector)
            volume_iqn = volume['provider_location'].split(' ')[1]

            (auth_method, auth_user, auth_pass) = \
                     volume['provider_auth'].split(' ', 3)

        # Add initiator iqns to target ACL
            try:
                self._execute('cinder-rtstool', 'add-initiator',
                          volume_iqn,
                          auth_user,
                          auth_pass,
                          connector['initiator'],
                          run_as_root=True)
            except putils.ProcessExecutionError:
                LOG.error(_("Failed to add initiator iqn %s to target") % connector['initiator'])
                raise iexception.ISCSITargetAttachFailed(volume_id=volume['id'])

        iscsi_properties = self.iscsiobj._get_iscsi_properties(volume)
        try:
            self.initiator_manager.add_vol_initname_pair(volume['id'], connector['initiator'])
        except:
            LOG.warn('Failed to record the initiator for the volume %s'%volume['id'])
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }
        
    def ensure_export(self, context, volume):
         
        iscsi_name = "%s%s" % (self.configuration.iscsi_target_prefix,
                               volume['name'])

        volume_path = self._get_volume_devpath(volume['name'])
        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        model_update = self._ensure_export(
            context, volume,
            iscsi_name,
            volume_path,
            self.configuration.zfspool,
            self.configuration)
        if model_update:
            self.target_helper.db.volume_update(context, volume['id'], model_update)
            
    def _ensure_export(self, context, volume, iscsi_name, volume_path,
                      vg_name, conf, old_name=None):
        try:
            volume_info = self.target_helper.db.volume_get(context, volume['id'])
        except exception.NotFound:
            LOG.info(_("Skipping ensure_export. No iscsi_target "
                       "provision for volume: %s"), volume['id'])
            return

        (auth_method,
         auth_user,
         auth_pass) = volume_info['provider_auth'].split(' ', 3)
        chap_auth = self.target_helper._iscsi_authentication(auth_method,
                                               auth_user,
                                               auth_pass)

        iscsi_target = 1
        
        self.targetbase.create_iscsi_target(iscsi_name, iscsi_target, 0, volume_path,
                                 chap_auth, check_exit_code=False)
        
        self.ensure_patch(iscsi_name,auth_user,auth_pass,volume['id'])
        
    def _ensure_patch(self,iscsi_name,auth_usrid,auth_passwd,volid):
        initname=self.initiator_manager.get_vol_initname(volid)
        if initname is None or initname=='':
            LOG.warn('Failed to get initname for volume-%s'%volid)
            return
        try:
            self._execute('cinder-rtstool', 'add-initiator',
                          iscsi_name,
                          auth_usrid,
                          auth_passwd,
                          initname,
                          run_as_root=True)
        except:
            LOG.warn('Failed to add-initiator for volume-%s'%volid)                      

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """  
        if refresh:
            self._stats = self._update_volume_stats()

        return self._stats    
                                
    
class SurRemotefsDriver(remotefs.RemoteFSDriver):
    def __init__(self):
        pass

class SurFibreChannelDriver(driver.FibreChannelDriver):
    def __init__(self):
        pass
