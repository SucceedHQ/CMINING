import React, { useState, useEffect } from 'react';
import { 
  LayoutDashboard, KeyRound, Users, UserCog, Mail, Bell, 
  GitBranch, Bug, Settings, CircleDollarSign, LogOut, Loader2, Plus
} from 'lucide-react';
import axios from 'axios';

const BACKEND_URL = 'https://succeedhq.pythonanywhere.com';

function SidebarItem({ icon: Icon, label, isActive, onClick }: any) {
  return (
    <div 
      onClick={onClick}
      className={`flex items-center gap-3 px-4 py-3 rounded-lg cursor-pointer transition-colors ${isActive ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-gray-600 hover:bg-gray-100'}`}
    >
      <Icon size={20} className={isActive ? 'text-indigo-600' : 'text-gray-400'} />
      <span>{label}</span>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState('analytics');
  const [adminToken, setAdminToken] = useState<string | null>(null);
  const [loginInput, setLoginInput] = useState('');
  
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  // Modal State handling
  const [modalOpen, setModalOpen] = useState(false);
  const [modalType, setModalType] = useState('');
  const [modalInput1, setModalInput1] = useState('');
  const [modalInput2, setModalInput2] = useState('');

  const openModal = (type: string) => {
    setModalType(type);
    setModalInput1('');
    setModalInput2('');
    setModalOpen(true);
  };

  const handleCreate = async () => {
    try {
      const endpoint = modalType === 'keys' ? '/api/admin/keys' : '/api/admin/campaigns';
      const payload = modalType === 'keys' ? { key_value: modalInput1, owner_name: modalInput2 } : { keyword_text: modalInput1 };
      
      await axios.post(`${BACKEND_URL}${endpoint}`, payload, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      
      setModalOpen(false);
      // Hack to force data refresh
      const curr = activeTab;
      setActiveTab('analytics');
      setTimeout(() => setActiveTab(curr), 50);
    } catch (err: any) {
      alert('Error creating record: ' + (err.response?.data?.error || err.message));
    }
  };

  useEffect(() => {
    if (!adminToken) return;
    setLoading(true);
    let endpoint = '/api/admin/stats';
    if(activeTab === 'keys') endpoint = '/api/admin/keys';
    if(activeTab === 'workers') endpoint = '/api/admin/workers';
    if(activeTab === 'leads') endpoint = '/api/admin/leads';
    if(activeTab === 'campaigns') endpoint = '/api/admin/campaigns';
    if(activeTab === 'notifications') endpoint = '/api/admin/notify';
    if(activeTab === 'withdrawals') endpoint = '/api/admin/withdrawals';
    if(activeTab === 'earnings') endpoint = '/api/admin/earnings_rates';
    if(activeTab === 'versions') endpoint = '/api/admin/versions';
    if(activeTab === 'bugs') endpoint = '/api/admin/bugs';
    if(activeTab === 'settings') endpoint = '/api/admin/settings';

    if (['notifications', 'earnings', 'versions'].includes(activeTab)) {
      setLoading(false);
      return; // these are essentially form views, not GET views
    }

    axios.get(`${BACKEND_URL}${endpoint}`, { headers: { Authorization: `Bearer ${adminToken}` } })
      .then(res => {
         setData(res.data);
         setLoading(false);
      })
      .catch(err => {
         console.error(err);
         setData(null);
         setLoading(false);
      });
  }, [adminToken, activeTab]);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setAdminToken(loginInput);
  };

  if (!adminToken) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
        <div className="sm:mx-auto sm:w-full sm:max-w-md">
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">Sign in to CMining Admin</h2>
        </div>
        <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
          <div className="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10 border border-gray-100">
            <form onSubmit={handleLogin} className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-700">Admin Secret Key</label>
                <input type="password" required className="mt-1 appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500" value={loginInput} onChange={e => setLoginInput(e.target.value)} />
              </div>
              <button type="submit" className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700">Sign in</button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  const tabs = [
    { id: 'analytics', label: 'Analytics Charts', icon: LayoutDashboard },
    { id: 'keys', label: 'Access Keys', icon: KeyRound },
    { id: 'workers', label: 'Workers / Heartbeat', icon: Users },
    { id: 'leads', label: 'Leads / Inventory', icon: UserCog },
    { id: 'campaigns', label: 'Campaigns Editor', icon: Mail },
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'withdrawals', label: 'Withdrawals', icon: CircleDollarSign },
    { id: 'earnings', label: 'Earnings Rates', icon: CircleDollarSign },
    { id: 'versions', label: 'App Versions', icon: GitBranch },
    { id: 'bugs', label: 'Bug Reports', icon: Bug },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  const TableLayout = ({ columns, dataList }: any) => (
    <div className="overflow-x-auto bg-white rounded-lg shadow border border-gray-200">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>{columns.map((c: string) => <th key={c} className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{c}</th>)}</tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {dataList?.map((row: any, i: number) => (
             <tr key={i}>{Object.values(row).map((val: any, j: number) => <td key={j} className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{String(val)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      <div className="w-64 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-6 border-b border-gray-200">
          <h1 className="text-xl font-bold text-gray-900 tracking-tight">CMining<span className="text-indigo-600">Admin</span></h1>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-1">
          {tabs.map(t => (
            <SidebarItem key={t.id} icon={t.icon} label={t.label} isActive={activeTab === t.id} onClick={() => setActiveTab(t.id)} />
          ))}
        </div>
        <div className="p-4 border-t border-gray-200">
          <button onClick={() => setAdminToken(null)} className="flex items-center gap-2 text-red-600 hover:bg-red-50 w-full px-4 py-2 rounded-lg transition-colors font-medium">
            <LogOut size={20} /> Logout
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-8 fade-in">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-2xl font-semibold text-gray-900">{tabs.find(t => t.id === activeTab)?.label}</h2>
          {['keys', 'campaigns'].includes(activeTab) && (
            <button onClick={() => openModal(activeTab)} className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700">
              <Plus size={16} /> Add New
            </button>
          )}
        </div>
        
        {loading ? <div className="flex justify-center p-12"><Loader2 className="animate-spin text-indigo-600" size={32} /></div> : (
          <>
            {activeTab === 'analytics' && data && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8 mt-4">
                <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                  <h3 className="text-sm font-medium text-gray-500 mb-1">Active Workers</h3>
                  <p className="text-3xl font-bold text-gray-900">{data?.workers?.active}</p>
                </div>
                <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                  <h3 className="text-sm font-medium text-gray-500 mb-1">Total Leads Extracted</h3>
                  <p className="text-3xl font-bold text-gray-900">{data?.leads?.total}</p>
                </div>
                <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                  <h3 className="text-sm font-medium text-gray-500 mb-1">Successful Outreaches</h3>
                  <p className="text-3xl font-bold text-green-600">{data?.leads?.successes}</p>
                </div>
              </div>
            )}
            
            {activeTab === 'keys' && data?.keys && <TableLayout columns={['ID', 'Key', 'Owner', 'Active', 'Leads', 'Earnings']} dataList={data.keys} />}
            {activeTab === 'workers' && data?.workers && <TableLayout columns={['ID', 'Owner', 'Last Active', 'Active', 'Banned']} dataList={data.workers} />}
            {activeTab === 'leads' && data?.leads && <TableLayout columns={['ID', 'Name', 'Website', 'Status', 'Worker ID']} dataList={data.leads} />}
            {activeTab === 'campaigns' && data?.campaigns && <TableLayout columns={['ID', 'Keyword', 'Status', 'Results']} dataList={data.campaigns} />}
            {activeTab === 'withdrawals' && data?.withdrawals && <TableLayout columns={['ID', 'Amount', 'Worker ID']} dataList={data.withdrawals} />}
            {activeTab === 'bugs' && data?.bugs && <TableLayout columns={['ID', 'Title', 'Desc']} dataList={data.bugs} />}
            {activeTab === 'settings' && data?.settings && <pre className="bg-gray-800 text-green-400 p-4 rounded-lg">{JSON.stringify(data.settings, null, 2)}</pre>}
            
            {['notifications', 'earnings', 'versions'].includes(activeTab) && (
              <div className="bg-white border text-center border-gray-200 rounded-xl p-12 text-gray-500 shadow-sm flex flex-col items-center justify-center">
                 <div className="p-4 bg-gray-50 rounded-full mb-4">
                    <Settings size={32} className="text-gray-400" />
                 </div>
                 <p className="text-lg font-medium text-gray-900">Form Submission UI Required</p>
                 <p className="text-sm mt-1">This section accepts POST requests to configuration endpoints.</p>
              </div>
            )}
          </>
        )}
      </div>

      {modalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white p-6 rounded-lg shadow-xl w-96 max-w-[90%] fade-in">
            <h3 className="text-xl font-bold mb-4 text-gray-900 border-b pb-2">
              Add New {modalType === 'keys' ? 'Access Key' : 'Campaign Keyword'}
            </h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {modalType === 'keys' ? 'Key Value (e.g. JUDD-123)' : 'Keyword Text (e.g. Plumbers in NY)'}
                </label>
                <input 
                  type="text" 
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500" 
                  value={modalInput1} 
                  onChange={e => setModalInput1(e.target.value)} 
                  placeholder={modalType === 'keys' ? 'Enter random secure key' : 'Enter target search phrase'}
                />
              </div>
              {modalType === 'keys' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Owner Name (Worker Identifier)</label>
                  <input 
                    type="text" 
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500" 
                    value={modalInput2} 
                    onChange={e => setModalInput2(e.target.value)} 
                    placeholder="e.g. John Doe - Remote"
                  />
                </div>
              )}
              <div className="flex justify-end gap-3 mt-6 pt-4 border-t">
                <button onClick={() => setModalOpen(false)} className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md transition-colors">
                  Cancel
                </button>
                <button 
                  onClick={handleCreate} 
                  disabled={!modalInput1} 
                  className="px-4 py-2 bg-indigo-600 disabled:opacity-50 text-white text-sm font-medium rounded-md hover:bg-indigo-700 transition-colors"
                >
                  Create Now
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

