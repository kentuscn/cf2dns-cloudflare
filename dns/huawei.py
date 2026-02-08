#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Author/Mail: tongdongdong@outlook.com
# Reference1: https://github.com/huaweicloud/huaweicloud-sdk-python-v3/tree/ff7df92d2a496871c7c2d84dfd2a7f4e2467fff5/huaweicloud-sdk-dns/huaweicloudsdkdns/v2/model 
# Reference2: https://support.huaweicloud.com/api-dns/dns_api_65003.html
# REGION: https://developer.huaweicloud.com/endpoint
#
# 华为云 DNS 模型说明：
# - 每个 IP 一个独立的 recordset
# - 更新策略：先删除该线路所有旧记录，再逐条创建新记录

from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkdns.v2 import *
from huaweicloudsdkdns.v2.region.dns_region import DnsRegion
import json


class HuaWeiApi():
    def __init__(self, ACCESSID, SECRETKEY, REGION = 'cn-east-3'):
        self.AK = ACCESSID
        self.SK = SECRETKEY
        self.region = REGION
        self.client = DnsClient.new_builder().with_credentials(BasicCredentials(self.AK, self.SK)).with_region(DnsRegion.value_of(self.region)).build()
        self.zone_id = self.get_zones()
        # 缓存已删除的 recordset ID，避免重复删除
        self._deleted_ids = set()

    def _success_response(self, data=None):
        """ 构造成功响应，与主程序期望格式一致 """
        return {'code': 0, 'message': 'success', 'data': data}
    
    def _error_response(self, message):
        """ 构造错误响应，与主程序期望格式一致 """
        return {'code': -1, 'message': str(message)}

    def del_record(self, domain, record_id):
        """ 删除记录 """
        if record_id in self._deleted_ids:
            return self._success_response({'status': 'already_deleted'})
        try:
            request = DeleteRecordSetsRequest()
            request.zone_id = self.zone_id[domain + '.']
            request.recordset_id = record_id
            response = self.client.delete_record_sets(request)
            result = json.loads(str(response))
            self._deleted_ids.add(record_id)
            return self._success_response(result)
        except Exception as e:
            return self._error_response(e)

    def get_record(self, domain, length, sub_domain, record_type):
        """ 获取 DNS 记录，智能清理多IP的recordset """
        self._deleted_ids = set()
        
        try:
            request = ListRecordSetsWithLineRequest()
            request.limit = length
            request.type = record_type
            if sub_domain == '@':
                request.name = domain + "."
            else:
                request.name = sub_domain + '.' + domain + "."
            response = self.client.list_record_sets_with_line(request)
            data = json.loads(str(response))
            
            # 按线路分组 recordset
            line_recordsets = {}
            for record in data.get('recordsets', []):
                if (sub_domain == '@' and domain + "." == record['name']) or (sub_domain + '.' + domain + "." == record['name']):
                    line = record['line']
                    if line not in line_recordsets:
                        line_recordsets[line] = []
                    line_recordsets[line].append(record)
            
            # 智能清理：删除多IP的recordset，只保留单IP的
            records_temp = []
            for line, recordsets in line_recordsets.items():
                line_name = self.line_format(line)
                single_ip_rs = [rs for rs in recordsets if len(rs.get('records', [])) == 1]
                multi_ip_rs = [rs for rs in recordsets if len(rs.get('records', [])) > 1]
                
                # 删除所有多IP的recordset
                for rs in multi_ip_rs:
                    self.del_record(domain, rs['id'])
                
                # 只返回单IP的recordset
                for rs in single_ip_rs:
                    records_temp.append({
                        'id': rs['id'],
                        'line': line_name,
                        'value': rs['records'][0]
                    })
            
            return {'code': 0, 'data': {'records': records_temp}}
        except Exception as e:
            return {'code': -1, 'message': str(e), 'data': {'records': []}}

    def create_record(self, domain, sub_domain, value, record_type, line, ttl):
        """ 创建记录 """
        try:
            if sub_domain == '@':
                name = domain + "."
            else:
                name = sub_domain + '.' + domain + "."
            
            hw_line = self.line_format(line)
            request = CreateRecordSetWithLineRequest()
            request.zone_id = self.zone_id[domain + '.']
            request.body = CreateRecordSetWithLineReq(
                type = record_type,
                name = name,
                ttl = ttl,
                weight = 1,
                records = [value],
                line = hw_line
            )
            response = self.client.create_record_set_with_line(request)
            result = json.loads(str(response))
            return self._success_response(result)
        except Exception as e:
            return self._error_response(e)
        
    def update_record(self, domain, record_id, sub_domain, value, record_type, ttl):
        """ 直接更新记录 """
        if sub_domain == '@':
            name = domain + "."
        else:
            name = sub_domain + '.' + domain + "."
        
        try:
            request = UpdateRecordSetsRequest()
            request.zone_id = self.zone_id[domain + '.']
            request.recordset_id = record_id
            request.body = UpdateRecordSetsReq(
                name = name,
                type = record_type,
                ttl = ttl,
                records = [value]
            )
            response = self.client.update_record_sets(request)
            return json.loads(str(response)), True
        except Exception as e:
            return {'error': str(e)}, False
        
    def change_record(self, domain, record_id, sub_domain, value, record_type, line, ttl):
        """ 更新记录 - 优先直接更新，失败则删除后创建 """
        try:
            # 如果该 recordset 已被删除，直接创建新的
            if record_id in self._deleted_ids:
                return self.create_record(domain, sub_domain, value, record_type, line, ttl)
            
            # 尝试直接更新
            result, success = self.update_record(domain, record_id, sub_domain, value, record_type, ttl)
            if success:
                return self._success_response(result)
            
            # 更新失败，回退到删除+创建
            self.del_record(domain, record_id)
            return self.create_record(domain, sub_domain, value, record_type, line, ttl)
        except Exception as e:
            return self._error_response(e)

    def get_zones(self):
        request = ListPublicZonesRequest()
        response = self.client.list_public_zones(request)
        result = json.loads(str(response))
        zone_id = {}
        for zone in result['zones']:
            zone_id[zone['name']] = zone['id'] 
        return zone_id

    def line_format(self, line):
        lines = {
            '默认' : 'default_view',
            '电信' : 'Dianxin',
            '联通' : 'Liantong',
            '移动' : 'Yidong',
            '境外' : 'Abroad',
            'default_view' : '默认',
            'Dianxin' : '电信',
            'Liantong' : '联通',
            'Yidong' : '移动',
            'Abroad' : '境外',
        }
        return lines.get(line, line)

if __name__ == '__main__':
    hw_api = HuaWeiApi('WTTCWxxxxxxxxx84O0V', 'GXkG6D4X1Nxxxxxxxxxxxxxxxxxxxxx4lRg6lT')
    print(hw_api.get_record('xxxx.com', 100, '@', 'A'))
