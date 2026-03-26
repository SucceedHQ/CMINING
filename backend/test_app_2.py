import sys
import traceback
import os

sys.path.insert(0, r"c:\Users\USER\Documents\TOOLS\CMINING TOOL\CMining-Monorepo\backend")
os.environ['TESTING'] = 'true'
os.environ['ADMIN_SECRET_KEY'] = 'test-secret'

try:
    import app
    with app.app.app_context():
        app.app.config['TESTING'] = True
        client = app.app.test_client()
        
        # 2. Test /api/admin/keys
        print("\n--- /api/admin/keys ---")
        try:
            resp = client.get('/api/admin/keys', headers={'Authorization': "Bearer test-secret"})
            print(resp.status_code)
            if resp.status_code == 500:
                print("Response data:", resp.data)
        except Exception as e:
            traceback.print_exc()
            
        print("\n--- /api/admin/key_requests ---")
        try:
            resp = client.get('/api/admin/key_requests', headers={'Authorization': "Bearer test-secret"})
            print(resp.status_code)
            if resp.status_code == 500:
                print("Response data:", resp.data)
        except Exception as e:
            traceback.print_exc()
        
        # 3. Test /api/batch/keywords
        print("\n--- /api/batch/keywords ---")
        try:
            ak = app.AccessKey.query.first()
            if ak:
                resp = client.post('/api/batch/keywords', headers={'Authorization': f"Bearer {ak.key_value}"})
                print(resp.status_code)
                if resp.status_code == 500:
                    print("Response data:", resp.data)
            else:
                print("No AccessKey found to test keywords.")
        except Exception as e:
            traceback.print_exc()
            
        # Also check /api/request_key
        print("\n--- /api/request_key ---")
        try:
            resp = client.post('/api/request_key', json={"contact_info": "test@test.com"})
            print(resp.status_code)
            if resp.status_code == 500:
                print("Response data:", resp.data)
        except Exception as e:
            traceback.print_exc()
            
except Exception as e:
    traceback.print_exc()
