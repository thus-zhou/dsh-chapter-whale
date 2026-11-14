import json
import unittest
from manager import test_app as fixture
from manager import app as module
from integration import model_roles


class ProviderApiTests(unittest.TestCase):
    setUp=fixture.ManagerTests.setUp
    tearDown=fixture.ManagerTests.tearDown

    def initialize(self):
        path=self.root/'ai.json'
        path.write_text(json.dumps({'base_url':'https://one.invalid/v1','api_key':'PRIVATE-ONE','model':'same'}),encoding='utf-8')
        response=self.client.post('/api/ai/providers/migrate',headers=self.headers,json={})
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('PRIVATE-ONE',response.text)
        return response.json()

    def test_migration_binding_and_legacy_writes_stay_in_sync(self):
        doc=self.initialize()
        first=doc['default_binding']['provider_id']
        second=self.client.post('/api/ai/providers',headers=self.headers,json={'name':'second','base_url':'https://two.invalid/v1','api_key':'PRIVATE-TWO'}).json()['id']
        response=self.client.put('/api/ai/bindings',headers=self.headers,json={'roles':{'B':{'provider_id':second,'model_id':'same'}}})
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('PRIVATE-TWO',response.text)
        denied=self.client.delete('/api/ai/providers/'+second,headers=self.headers)
        self.assertEqual(denied.status_code,400)
        cleared=self.client.put('/api/ai/bindings',headers=self.headers,json={'roles':{'B':{}}})
        self.assertEqual(cleared.status_code,200,cleared.text)
        self.assertEqual(self.client.delete('/api/ai/providers/'+second,headers=self.headers).status_code,200)
        updated=self.client.put('/api/ai',headers=self.headers,json={'base_url':'https://one.invalid/v1','model':'new'})
        self.assertEqual(updated.status_code,200,updated.text)
        current=json.loads((self.root/'ai.json').read_text(encoding='utf-8'))
        self.assertEqual(current['default_binding'],{'provider_id':first,'model_id':'new','fallbacks':[]})
        self.assertNotIn('PRIVATE-ONE',(self.root/'ai.json').read_text(encoding='utf-8'))
        self.assertEqual(model_roles.connection('B',module.load_ai())['api_key'],'PRIVATE-ONE')

    def test_invalid_binding_and_price_do_not_modify_file(self):
        doc=self.initialize();path=self.root/'ai.json';original=path.read_bytes()
        for fallback in ([None],['invalid']):
            response=self.client.put('/api/ai/bindings',headers=self.headers,json={'default_binding':{**doc['default_binding'],'fallbacks':fallback}})
            self.assertEqual(response.status_code,400,response.text)
            self.assertEqual(path.read_bytes(),original)
        response=self.client.put('/api/ai/providers/'+doc['default_binding']['provider_id'],headers=self.headers,json={'pricing':{'same':{'input':'-1','output':'2'}}})
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(path.read_bytes(),original)
