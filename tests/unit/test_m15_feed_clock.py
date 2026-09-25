from datetime import UTC, datetime
import importlib.util
import json
import math
from pathlib import Path
import queue
import socket
import struct
import tempfile
import unittest
from unittest.mock import patch
from scripts import m15_feed_clock as c


def row(host,index,rtt=.1,offset=.01,valid=True):
    return {'host':host,'sample_index':index,'valid':valid,'roundtrip_seconds':rtt,'offset_seconds':offset}


def ntp():
    return {'platform':'win32','samples':[row(host,0) for host in c.HOSTS],'wall_clock_continuous':True}


def cross(offset=0,rtt=.002):
    return {'selected':row('pipe',0,rtt,offset),'wall_clock_continuous':True}


class ClockTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def test_minimum_rtt_never_chooses_based_on_passing_offset(self):
        data=[row(c.HOSTS[0],0,.01,.8),row(c.HOSTS[0],1,.1,0),row(c.HOSTS[0],2,.2,0)]
        selected=c.select_samples(data)[0]
        self.assertEqual(selected['selected_sample_index'],0)
        self.assertEqual(selected['offset_seconds'],.8)

    def test_invalid_nonfinite_low_rtt_excluded_tie_uses_index(self):
        data=[row(c.HOSTS[0],2,.2),row(c.HOSTS[0],1,.2),row(c.HOSTS[0],0,.01,valid=False)]
        self.assertEqual(c.select_samples(data)[0]['selected_sample_index'],1)
        self.assertFalse(c.select_samples([row(c.HOSTS[0],0,float('nan'))])[0]['valid'])

    def test_fixed_three_samples_and_original_timeouts(self):
        output=queue.Queue()
        with patch.object(c.socket,'gethostbyname',return_value='127.0.0.1'),patch.object(c,'probe',return_value={'valid':True}) as probe,patch.object(c.time,'sleep'),patch.object(c.time,'monotonic',return_value=0):
            c.collect_host(c.HOSTS[0],100,output)
        self.assertEqual(probe.call_count,3)
        self.assertEqual(c.TOTAL_BUDGET_SECONDS,12)
        self.assertEqual(c.MAX_CLOCK_BOUND_SECONDS,.5)

    def test_all_six_raw_slots_and_missing_budget_preserved(self):
        def worker(host,deadline,out):
            for index in range(3):out.put(row(host,index,.1+index))
        result=c.collect(worker=worker,budget=.2)
        self.assertEqual(len(result['raw_samples']),6)
        missing=c.collect(worker=lambda *a:None,budget=.01)
        self.assertEqual(len(missing['raw_samples']),6)
        self.assertFalse(any(r['valid'] for r in missing['samples']))

    def test_dns_is_before_t1_in_sampler(self):
        # Resolve belongs to host collection and probe accepts an already resolved IP.
        with patch.object(c.socket,'gethostbyname',return_value='192.0.2.1') as resolve,patch.object(c,'probe',return_value={'valid':False}) as probe,patch.object(c.time,'sleep'),patch.object(c.time,'monotonic',return_value=0):
            c.collect_host(c.HOSTS[0],10,queue.Queue())
        resolve.assert_called_once_with(c.HOSTS[0])
        self.assertTrue(all(call.args[0]=='192.0.2.1' for call in probe.call_args_list))

    def test_both_os_quality_pass_and_same_source_decimal_bound(self):
        result=c.assess_time_quality(ntp(),cross())
        self.assertTrue(result['quality_passed'])
        self.assertAlmostEqual(result['wsl']['estimates'][0]['bound_seconds'],.061)

    def test_windows_good_but_wsl_offset_fails(self):
        result=c.assess_time_quality(ntp(),cross(offset=.6))
        self.assertTrue(result['windows']['quality_passed'])
        self.assertFalse(result['quality_passed'])
        self.assertFalse(result['wsl']['quality_passed'])

    def test_windows_good_and_relation_good_but_combined_wsl_bound_fails(self):
        result=c.assess_time_quality(ntp(),cross(offset=.46,rtt=.01))
        self.assertTrue(result['cross_clock']['quality_passed'])
        self.assertFalse(result['wsl']['quality_passed'])

    def test_offset_sign_derives_wsl_without_comparing_monotonic_origins(self):
        data=ntp();data['samples']=[row(h,0,.2,.2) for h in c.HOSTS]
        result=c.assess_time_quality(data,cross(offset=-.1,rtt=.02))
        self.assertAlmostEqual(result['wsl']['estimates'][0]['derived_offset_seconds'],.1)
        self.assertAlmostEqual(result['wsl']['estimates'][0]['bound_seconds'],.21)

    def test_missing_host_invalid_platform_no_valid_or_missing_handshake(self):
        data=ntp();data['samples'][1]['valid']=False
        result=c.assess_time_quality(data,cross())
        self.assertTrue(result['reception_allowed']);self.assertFalse(result['quality_passed'])
        data['samples'][0]['valid']=False
        self.assertFalse(c.assess_time_quality(data,cross())['reception_allowed'])
        data=ntp();data['platform']='linux'
        self.assertFalse(c.assess_time_quality(data,cross())['reception_allowed'])
        self.assertFalse(c.assess_time_quality(ntp(),{})['quality_passed'])

    def test_handshake_known_offset_timestamps_and_clock_step_reject(self):
        reply={'id':1,'t2':100.21,'t3':100.211,'windows_monotonic_elapsed':.001}
        result=c.handshake_sample(reply,1,100,100.021,1,1.021)
        self.assertTrue(result['valid']);self.assertAlmostEqual(result['offset_seconds'],.2)
        self.assertAlmostEqual(result['roundtrip_seconds'],.02)
        self.assertFalse(c.handshake_sample(reply,1,100,100.021,1,1.2)['valid'])
        reply['id']=2
        self.assertFalse(c.handshake_sample(reply,1,100,100.021,1,1.021)['valid'])

    def test_wall_clock_jump_preserves_raw_but_invalidates_selection(self):
        def worker(host,deadline,out):
            for index in range(3):out.put(row(host,index))
        with patch.object(c.time,'time',side_effect=[100,102]):result=c.collect(worker=worker,budget=.2)
        self.assertTrue(all(r['valid'] for r in result['raw_samples']))
        self.assertFalse(any(r['valid'] for r in result['samples']))

    def test_packet_identity_clock_and_modes(self):
        request=bytearray(48);request[0]=35;struct.pack_into('!II',request,40,2208988900,0)
        response=bytearray(48);response[0]=36;response[1]=2;response[24:32]=request[40:48]
        struct.pack_into('!II',response,32,2208988900,2**28)
        struct.pack_into('!II',response,40,2208988900,2**29)
        self.assertTrue(c.decode(response,request,100,100.2,1,1.2)['valid'])
        response[0]=35
        self.assertFalse(c.decode(response,request,100,100.2,1,1.2)['valid'])

    def test_kiss_of_death_halts_requests_without_positive_retry(self):
        output=queue.Queue()
        with patch.object(c.socket,'gethostbyname',return_value='127.0.0.1'),patch.object(c,'probe',return_value={'valid':False,'kiss_of_death':True}) as probe,patch.object(c.time,'sleep'),patch.object(c.time,'monotonic',return_value=0):
            c.collect_host(c.HOSTS[0],100,output)
        self.assertEqual(probe.call_count,1);self.assertEqual(output.qsize(),3)

    def test_archive_not_overwritten_and_periodic_offsets_fixed(self):
        with tempfile.TemporaryDirectory() as base:
            output=Path(base)/'sample'
            with patch.object(c,'_run_windows',return_value=ntp()) as run,patch.object(c,'collect_cross_clock',return_value=cross()):
                result=c.collect_time_quality('fake-python',output,binding={'run_id':'mock-run'})
                self.assertTrue(result['quality_passed'])
                self.assertEqual(result['run_binding'],{'run_id':'mock-run'})
                self.assertEqual(set(result['raw_sha256']),{'windows-ntp.json','windows-wsl-handshake.json'})
                with self.assertRaises(FileExistsError):c.collect_time_quality('fake-python',output)
                self.assertEqual(run.call_count,1)
            raw=json.loads((output/'windows-ntp.json').read_text())
            self.assertEqual(raw['measurement_id'],result['measurement_id'])
            self.assertEqual(raw['run_binding'],result['run_binding'])
            self.assertTrue((output/'windows-ntp.json').is_file())
            self.assertTrue((output/'windows-wsl-handshake.json').is_file())
        self.assertEqual(c.periodic_offsets(3601),(1800,3600))

    def test_malformed_samples_and_clock_discontinuity_cannot_pass(self):
        data=ntp();data['samples']=None
        self.assertFalse(c.assess_time_quality(data,cross())['reception_allowed'])
        data=ntp();data['wall_clock_continuous']=False
        self.assertFalse(c.assess_time_quality(data,cross())['reception_allowed'])

    def test_ntp_worker_timeout_still_preserves_assessment_no_retries(self):
        with tempfile.TemporaryDirectory() as base:
            with patch.object(c,'_run_windows',side_effect=TimeoutError) as run,patch.object(c,'collect_cross_clock',return_value=cross()):
                result=c.collect_time_quality('fake',Path(base)/'sample')
            self.assertFalse(result['reception_allowed']);self.assertFalse(result['quality_passed'])
            self.assertEqual(run.call_count,1)

if __name__=='__main__':unittest.main()
