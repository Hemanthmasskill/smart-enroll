import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../../components/PageHeader";
import StatCard from "../../components/StatCard";
import StatusBadge from "../../components/StatusBadge";
import { getAdminDashboard, getPrograms } from "../../services/api";
import "./Admin.css";

export default function AdminDashboard(){
  const [data,setData]=useState(null); const [programs,setPrograms]=useState([]); const navigate=useNavigate();
  useEffect(()=>{Promise.all([getAdminDashboard(),getPrograms()]).then(([d,p])=>{setData(d);setPrograms(p);});},[]);
  if(!data) return <p>Loading admin dashboard...</p>;
  const programName=(id)=>programs.find(p=>p.id===id)?.name ?? id;
  return <div><PageHeader title="Admin Dashboard" subtitle="Monitor autonomous admission processing, applications, and exceptions." />
    <div className="admin-stat-grid"><StatCard label="Total Applications" value={data.stats.total}/><StatCard label="Processing" value={data.stats.processing}/><StatCard label="Waiting for Documents" value={data.stats.waitingForDocuments}/><StatCard label="Eligible" value={data.stats.eligible}/><StatCard label="Open Exceptions" value={data.stats.exceptions}/></div>
    <div className="admin-grid-2"><section className="card admin-panel"><div className="admin-panel-head"><span className="admin-panel-title">Recent Applications</span><button className="admin-link" onClick={()=>navigate('/admin/applications')}>View all</button></div><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Application</th><th>Applicant</th><th>Programme</th><th>Status</th></tr></thead><tbody>{data.recentApplications.map(a=><tr key={a.applicationId}><td><button className="admin-link" onClick={()=>navigate(`/admin/applications/${a.applicationId}`)}>{a.applicationId}</button></td><td>{a.applicantName}</td><td>{programName(a.programmeId)}</td><td><StatusBadge code={a.status}/></td></tr>)}</tbody></table></div></section>
    <section className="card admin-panel"><div className="admin-panel-head"><span className="admin-panel-title">Attention Required</span><button className="admin-link" onClick={()=>navigate('/admin/exceptions')}>View exceptions</button></div><div className="admin-exception-list">{data.recentExceptions.map(e=><div className="admin-exception" key={e.id}><div className="admin-exception-top"><span className="admin-exception-title">{e.type.replaceAll('_',' ')}</span><span className={`severity-${e.severity}`}>{e.severity}</span></div><p className="admin-muted">{e.applicationId} · {e.applicantName}</p><p style={{fontSize:'13px',marginTop:'6px'}}>{e.description}</p></div>)}</div></section></div>
  </div>;
}
