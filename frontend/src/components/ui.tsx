import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import type { ExecutionStatus, TicketStatus } from '../types'
import { useAuth } from '../auth/AuthContext'

export function Shell({ children, title }: { children: ReactNode; title: string }) {
  const auth = useAuth()
  return <div className="app-shell">
    <aside className="sidebar">
      <Link className="brand" to="/"><span className="brand-mark">N</span><span>northstar<span className="brand-sub">SUPPORT DESK</span></span></Link>
      <div className="nav-label">WORKSPACE</div>
      <nav className="nav-list" aria-label="Main navigation">
        <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><span className="nav-icon">◫</span>Overview</NavLink>
        <NavLink to="/tickets" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><span className="nav-icon">▤</span>Tickets</NavLink>
        {auth.status?.permissions.reviewer && <NavLink to="/approvals" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><span className="nav-icon">♧</span>Refund approvals</NavLink>}
      </nav>
      <div className="sidebar-bottom"><span className="online-dot" /> All systems operational</div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="mobile-brand"><span className="brand-mark">N</span> Northstar</div><div className="breadcrumbs">Support workspace <span>/</span> <strong>{title}</strong></div><div className="profile"><span className="profile-avatar">{(auth.status?.user?.name || 'SD').split(' ').map(part => part[0]).slice(0, 2).join('')}</span><span><b>{auth.status?.user?.name || 'Support desk'}</b><small>{auth.status?.permissions.reviewer ? 'Reviewer workspace' : 'Agent workspace'}</small></span><button className="text-button logout-button" onClick={() => void auth.logout()}>Sign out</button></div></header>
      <div className="page-content">{children}</div>
    </main>
  </div>
}

export function PageTitle({ eyebrow, title, subtitle, action }: { eyebrow?: string; title: string; subtitle?: string; action?: ReactNode }) {
  return <div className="page-title-row"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{action && <div className="title-action">{action}</div>}</div>
}

export function StatusBadge({ status }: { status: TicketStatus | ExecutionStatus | string }) {
  const label = status.replaceAll('_', ' ')
  return <span className={`badge badge-${status.replaceAll('_', '-')}`}>{label}</span>
}

export function Loading({ label = 'Loading workspace' }: { label?: string }) { return <div className="loading-state"><span className="spinner" /><span>{label}</span></div> }
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) { return <div className="error-state"><span className="error-icon">!</span><div><b>We couldn’t load this view</b><p>{message}</p>{onRetry && <button className="button button-outline button-small" onClick={onRetry}>Try again</button>}</div></div> }
export function EmptyState({ title, detail }: { title: string; detail: string }) { return <div className="empty-state"><span className="empty-icon">✳</span><b>{title}</b><p>{detail}</p></div> }
export function Panel({ title, subtitle, action, children, className = '' }: { title: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><div className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>
}
