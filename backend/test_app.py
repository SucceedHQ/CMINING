import sys
import traceback
import os

sys.path.insert(0, r"c:\Users\USER\Documents\TOOLS\CMINING TOOL\CMining-Monorepo\backend")
os.environ['TESTING'] = 'true'

try:
    import app
    with app.app.app_context():
        app.app.config['TESTING'] = True
        client = app.app.test_client()
        
        # 1. Test /api/worker/request_key
        print("--- /api/worker/request_key ---")
        try:
            resp = client.post('/api/worker/request_key', json={"contact_info": "test@test.com", "worker_name": "TestWorker"})
            print(resp.status_code, resp.data.decode('utf-8'))
        except Exception as e:
            traceback.print_exc()

        # 2. Test /api/admin/keys
        print("\n--- /api/admin/keys ---")
        try:
            resp = client.get('/api/admin/keys', headers={'Authorization': f"Bearer {app.ADMIN_SECRET_KEY}"})
            print(resp.status_code, resp.data.decode('utf-8'))
        except Exception as e:
            traceback.print_exc()
        
        # 3. Test /api/batch/keywords
        print("\n--- /api/batch/keywords ---")
        try:
            ak = app.AccessKey.query.first()
            if ak:
                resp = client.get('/api/batch/keywords', headers={'Authorization': f"Bearer {ak.key_value}"})
                print(resp.status_code, resp.data.decode('utf-8'))
            else:
                print("No AccessKey found to test keywords.")
        except Exception as e:
            traceback.print_exc()
except Exception as e:
    traceback.print_exc()
