import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../../components/PageHeader";
import StatusBadge from "../../components/StatusBadge";
import { getAdminApplications, getPrograms } from "../../services/api";
import "./Admin.css";
export default function Applications(){
 const [apps,setApps]=useState([]),[programs,setPrograms]=useState([]),[search,setSearch]=useState(''),[status,setStatus]=useState('ALL'),[program,setProgram]=useState('ALL'); const navigate=useNavigate();
 useEffect(()=>{Promise.all([getAdminApplications(),getPrograms()]).then(([a,p])=>{setApps(a);setPrograms(p);});},[]);
 const filtered=useMemo(()=>apps.filter(a=>{const q=search.toLowerCase(); return (!q||a.applicationId.toLowerCase().includes(q)||a.applicantName.toLowerCase().includes(q))&&(status==='ALL'||a.status===status)&&(program==='ALL'||a.programmeId===program)}),[apps,search,status,program]);
 const pn=id=>programs.find(p=>p.id===id)?.name??id;
 return <div><PageHeader title="Applications" subtitle="Monitor admission cases and inspect their autonomous processing state."/><section className="card admin-panel"><div className="admin-controls"><input className="admin-control admin-search" placeholder="Search application ID or applicant" value={search} onChange={e=>setSearch(e.target.value)}/><select className="admin-control" value={status} onChange={e=>setStatus(e.target.value)}><option value="ALL">All statuses</option>{[...new Set(apps.map(a=>a.status))].map(s=><option key={s}>{s}</option>)}</select><select className="admin-control" value={program} onChange={e=>setProgram(e.target.value)}><option value="ALL">All programmes</option>{programs.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
 <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Application ID</th><th>Applicant</th><th>Programme</th><th>Submitted</th><th>Documents</th><th>Eligibility</th><th>Status</th><th>Action</th></tr></thead><tbody>{filtered.map(a=><tr key={a.applicationId}><td>{a.applicationId}</td><td>{a.applicantName}</td><td>{pn(a.programmeId)}</td><td>{a.submittedAt}</td><td>{a.documentStatus}</td><td><StatusBadge code={a.eligibilityStatus}/></td><td><StatusBadge code={a.status}/></td><td><button className="admin-link" onClick={()=>navigate(`/admin/applications/${a.applicationId}`)}>View Details</button></td></tr>)}</tbody></table>{!filtered.length&&<p className="admin-empty">No applications match these filters.</p>}</div></section></div>;
}
