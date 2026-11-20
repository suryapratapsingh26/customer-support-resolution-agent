import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { BrowserRouter, Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from './api/client'
import { supportApi } from './api/support'
import { useDashboard } from './hooks/useDashboard'
import { EmptyState, ErrorState, Loading, PageTitle, Panel, Shell, StatusBadge } from './components/ui'
import type { AgentExecution, AgentMessage, Customer, Order, RefundApproval, RefundExecutionResult, Ticket } from './types'

function DashboardPage() {
  const data = useDashboard()
  const [pending, setPending] = useState<number | null>(null)
  useEffect(() => {
    if (window.supportDashboardHost) supportApi.pendingApprovals().then(rows => setPending(rows.length)).catch(() => setPending(null))
  }, [])
  if (data.loading) return <Shell title="Overview"><Loading /></Shell>
  if (data.error) return <Shell title="Overview"><PageTitle eyebrow="SUPPORT OVERVIEW" title="Welcome back" subtitle="Here’s what’s happening across your support desk." /><ErrorState message={data.error} onRetry={data.reload} /></Shell>
  const open = data.tickets.filter(t => t.status === 'open' || t.status === 'in_progress').length
  return <Shell title="Overview">
    <PageTitle eyebrow="SUPPORT OVERVIEW" title="Welcome back" subtitle="Here’s what’s happening across your support desk." action={<Link to="/tickets" className="button button-primary">View tickets <span>→</span></Link>} />
    <div className="stat-grid">
      <StatCard label="Open tickets" value={open} note="Across your assigned customers" icon="▤" tone="blue" />
      <StatCard label="Total tickets" value={data.tickets.length} note="In your authorized queue" icon="◷" tone="violet" />
      <StatCard label="Customers" value={data.customers.length} note="Available in this workspace" icon="♙" tone="green" />
      <StatCard label="Refund approvals" value={pending ?? '—'} note={pending === null ? 'Reviewer access unavailable' : 'Awaiting your review'} icon="♧" tone="amber" />
    </div>
    <div className="dashboard-grid">
      <Panel title="Recent tickets" subtitle="The latest customer conversations" action={<Link className="text-link" to="/tickets">All tickets <span>→</span></Link>}>
        <TicketTable tickets={data.tickets.slice(0, 5)} customers={data.customers} />
        {data.tickets.length === 0 && <EmptyState title="No tickets in your queue" detail="New tickets will appear here when they are assigned to your authorized customers." />}
      </Panel>
      <Panel title="Needs attention" subtitle="Work that may need your input">
        {pending === null ? <div className="notice-card"><span>♧</span><div><b>Reviewer connection needed</b><p>Configure reviewer access to load refund requests.</p></div></div> : pending > 0 ? <Link to="/approvals" className="notice-card clickable"><span className="notice-icon amber">♧</span><div><b>{pending} approval{pending === 1 ? '' : 's'} waiting</b><p>Review refund requests that need a decision.</p></div><span className="notice-arrow">→</span></Link> : <div className="notice-card"><span className="notice-icon green">✓</span><div><b>You’re all caught up</b><p>No refund approvals are waiting for review.</p></div></div>}
        <div className="attention-divider" />
        <div className="mini-note"><span className="note-dot" /><div><b>AI recommendations are advisory</b><p>Refunds always require a separate human approval.</p></div></div>
      </Panel>
    </div>
    <div className="integration-note"><span>i</span><p><b>Connected workspace</b> Ticket access is provided by your organization’s identity integration. Only assigned customer records are shown.</p></div>
  </Shell>
}

function StatCard({ label, value, note, icon, tone }: { label: string; value: number | string; note: string; icon: string; tone: string }) {
  return <div className="stat-card"><div className={`stat-icon ${tone}`}>{icon}</div><div className="stat-label">{label}</div><div className="stat-value">{value}</div><div className="stat-note">{note}</div></div>
}

function TicketsPage() {
  const { tickets, customers, loading, error, reload } = useDashboard()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const visible = useMemo(() => tickets.filter(t => {
    const customer = customers.find(c => c.id === t.customer_id)
    const matchesText = `${t.subject} ${t.description} ${customer?.name ?? ''} ${t.id}`.toLowerCase().includes(query.toLowerCase())
    const matchesStatus = filter === 'all' || t.status === filter
    return matchesText && matchesStatus
  }), [tickets, customers, query, filter])
  return <Shell title="Tickets">
    <PageTitle eyebrow="CUSTOMER SUPPORT" title="Tickets" subtitle="Search, triage, and work through your customer queue." />
    <Panel title="Ticket queue" subtitle={`${visible.length} of ${tickets.length} tickets`} className="table-panel">
      <div className="table-toolbar"><label className="search-box"><span>⌕</span><input aria-label="Search tickets" placeholder="Search by customer, subject, or ticket ID" value={query} onChange={e => setQuery(e.target.value)} /></label><label className="filter-label"><span>Status</span><select aria-label="Filter by status" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All statuses</option><option value="open">Open</option><option value="in_progress">In progress</option><option value="resolved">Resolved</option><option value="closed">Closed</option></select></label></div>
      {loading ? <Loading label="Loading ticket queue" /> : error ? <ErrorState message={error} onRetry={reload} /> : visible.length ? <TicketTable tickets={visible} customers={customers} /> : <EmptyState title={tickets.length ? 'No matching tickets' : 'No tickets yet'} detail={tickets.length ? 'Try changing your search or status filter.' : 'Tickets assigned to your authorized customers will appear here.'} />}
    </Panel>
  </Shell>
}

function TicketTable({ tickets, customers }: { tickets: Ticket[]; customers: Customer[] }) {
  return <div className="table-wrap"><table className="data-table"><thead><tr><th>Ticket</th><th>Customer</th><th>Order</th><th>Status</th></tr></thead><tbody>{tickets.map(ticket => <tr key={ticket.id}><td><Link className="ticket-cell" to={`/tickets/${ticket.id}`}><span className="ticket-hash">#{ticket.id}</span><b>{ticket.subject}</b><small>{ticket.description}</small></Link></td><td><CustomerCell customer={customers.find(c => c.id === ticket.customer_id)} /></td><td>{ticket.order_id ? <span className="mono">#{ticket.order_id}</span> : <span className="muted">—</span>}</td><td><StatusBadge status={ticket.status} /></td></tr>)}</tbody></table></div>
}

function CustomerCell({ customer }: { customer?: Customer }) {
  if (!customer) return <span className="muted">Customer unavailable</span>
  return <span className="customer-cell"><span className="customer-avatar">{customer.name.split(' ').map(part => part[0]).slice(0, 2).join('')}</span><span><b>{customer.name}</b><small>{customer.email}</small></span></span>
}

function TicketDetailPage() {
  const { ticketId } = useParams()
  const id = Number(ticketId)
  const { tickets, customers, loading, error, reload } = useDashboard()
  const ticket = tickets.find(t => t.id === id)
  const customer = ticket ? customers.find(c => c.id === ticket.customer_id) : undefined
  const [order, setOrder] = useState<Order | null>(null)
  const [detailError, setDetailError] = useState('')
  useEffect(() => {
    if (!ticket?.order_id) { setOrder(null); return }
    supportApi.order(ticket.order_id, ticket.customer_id).then(setOrder).catch(err => setDetailError(err.message))
  }, [ticket?.id, ticket?.order_id, ticket?.customer_id])
  if (loading) return <Shell title="Ticket details"><Loading /></Shell>
  if (error) return <Shell title="Ticket details"><ErrorState message={error} onRetry={reload} /></Shell>
  if (!ticket) return <Shell title="Ticket details"><div className="back-link"><Link to="/tickets">← Back to tickets</Link></div><EmptyState title="Ticket not found" detail="This ticket may not be assigned to your authorized customer list." /></Shell>
  return <Shell title={`Ticket #${ticket.id}`}>
    <div className="back-link"><Link to="/tickets">← All tickets</Link><span>/</span><span>Ticket #{ticket.id}</span></div>
    <PageTitle eyebrow={`TICKET #${ticket.id}`} title={ticket.subject} subtitle="Review the case details and continue the customer conversation." action={<StatusBadge status={ticket.status} />} />
    <div className="ticket-detail-grid">
      <div className="detail-main">
        <Panel title="Customer conversation" subtitle="AI support agent · recommendations require human review"><AgentPanel ticket={ticket} /></Panel>
        <Panel title="Ticket description"><p className="description-text">{ticket.description}</p></Panel>
      </div>
      <aside className="detail-side">
        <Panel title="Customer"><CustomerCell customer={customer} />{customer && <div className="detail-meta"><span>Customer ID</span><b>#{customer.id}</b></div>}</Panel>
        <Panel title="Order details" subtitle={ticket.order_id ? `Order #${ticket.order_id}` : undefined}>
          {!ticket.order_id ? <div className="muted-block">No order is linked to this ticket.</div> : detailError ? <div className="inline-error">{detailError}</div> : order ? <><div className="order-status"><span>Order status</span><StatusBadge status={order.status} /></div><div className="detail-meta"><span>Items</span><b>{order.items.length}</b></div><div className="order-items">{order.items.map(item => <div className="order-item" key={item.id}><span className="item-thumb">▧</span><span><b>{item.product_name}</b><small>Qty {item.quantity}</small></span><strong>{item.unit_price.toLocaleString('en-IN')} <small>INR</small></strong></div>)}</div></> : <Loading label="Loading order" />}
          <div className="data-limitation"><b>Payment & shipment data</b><p>The current API does not expose customer-scoped payment or shipment detail endpoints for this dashboard.</p></div>
        </Panel>
        <Panel title="Execution activity" subtitle="Saved agent runs"><ExecutionHistory ticket={ticket} /></Panel>
      </aside>
    </div>
  </Shell>
}

function AgentPanel({ ticket }: { ticket: Ticket }) {
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [execution, setExecution] = useState<AgentExecution | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState('')
  const pendingMessage = useRef<{ content: string; key: string } | null>(null)
  const sessionKey = `northstar-agent-session-${ticket.id}`
  const loadSession = async (existingId?: number) => {
    setLoading(true); setError('')
    try {
      const id = existingId ?? Number(sessionStorage.getItem(sessionKey))
      if (!id) { setSessionId(null); setMessages([]); setExecution(null); return }
      const [conversation, status, executions] = await Promise.all([
        supportApi.conversation(ticket.customer_id, id),
        supportApi.sessionStatus(ticket.customer_id, id),
        supportApi.executions(ticket.customer_id, ticket.id),
      ])
      setSessionId(id); setMessages(conversation.messages); setExecution(status.current_execution ?? executions.find(row => row.session_id === id) ?? null)
    } catch (err) { setError(err instanceof Error ? err.message : 'Conversation could not be loaded.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void loadSession() }, [ticket.id])
  const start = async () => {
    setBusy(true); setError('')
    try {
      const keyName = `${sessionKey}-create-key`
      let key = sessionStorage.getItem(keyName)
      if (!key) { key = `ticket-${ticket.id}-${crypto.randomUUID()}`; sessionStorage.setItem(keyName, key) }
      const session = await supportApi.createSession(ticket, key)
      sessionStorage.setItem(sessionKey, String(session.id))
      await loadSession(session.id)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not start an agent session.') }
    finally { setBusy(false) }
  }
  const send = async (event: FormEvent) => {
    event.preventDefault()
    if (!sessionId || !draft.trim() || busy) return
    const content = draft.trim()
    const request = pendingMessage.current?.content === content
      ? pendingMessage.current
      : { content, key: `message-${crypto.randomUUID()}` }
    pendingMessage.current = request
    const key = request.key
    setBusy(true); setError('')
    try {
      const result = await supportApi.sendMessage(ticket.customer_id, sessionId, content, key)
      setExecution(result.execution)
      const conversation = await supportApi.conversation(ticket.customer_id, sessionId)
      setMessages(conversation.messages); setDraft(''); pendingMessage.current = null
    } catch (err) {
      if (err instanceof ApiError && err.status === 503 && err.executionId) {
        try {
          const failed = await supportApi.execution(ticket.customer_id, err.executionId)
          const conversation = await supportApi.conversation(ticket.customer_id, sessionId)
          setExecution(failed); setMessages(conversation.messages); setDraft(''); pendingMessage.current = null
          setError('')
        } catch {
          setError(err.message)
        }
      } else setError(err instanceof Error ? err.message : 'Message could not be sent.')
    }
    finally { setBusy(false) }
  }
  const refresh = () => { if (sessionId) void loadSession(sessionId) }
  const cancel = async () => {
    if (!execution || !sessionId || !window.confirm('Cancel this agent execution?')) return
    setBusy(true)
    try { setExecution(await supportApi.cancelExecution(ticket.customer_id, execution.id)); await loadSession(sessionId) }
    catch (err) { setError(err instanceof Error ? err.message : 'Execution could not be cancelled.') }
    finally { setBusy(false) }
  }
  if (loading) return <div className="agent-body"><Loading label="Loading conversation" /></div>
  if (error && !sessionId) return <div className="agent-body"><ErrorState message={error} onRetry={refresh} /></div>
  if (!sessionId) return <div className="agent-start"><div className="agent-illustration"><span>✳</span><i /><i /><i /></div><div><b>Get help investigating this ticket</b><p>Start a secure agent session to review the ticket and receive a grounded resolution recommendation.</p></div><button className="button button-primary" disabled={busy} onClick={start}>{busy ? 'Starting…' : 'Start agent session'} <span>→</span></button>{error && <div className="inline-error">{error}</div>}</div>
  const canCancel = execution && ['pending', 'running', 'waiting_for_approval'].includes(execution.status)
  return <div className="agent-body">
    <div className="agent-toolbar"><div className="agent-identity"><span className="agent-avatar">✳</span><span><b>Northstar AI</b><small><span className="online-dot" /> Session #{sessionId}</small></span></div><div className="toolbar-actions"><button className="icon-button" onClick={refresh} aria-label="Refresh execution status" title="Refresh status">↻</button>{canCancel && <button className="button button-outline button-small" disabled={busy} onClick={cancel}>Cancel execution</button>}</div></div>
    {error && <div className="inline-error message-error">{error}</div>}
    {execution && <div className="execution-strip"><div><span className="execution-label">CURRENT EXECUTION</span><b>Run #{execution.id}</b></div><StatusBadge status={execution.status} /><button className="text-button" onClick={refresh}>Refresh status</button></div>}
    <div className="messages" aria-live="polite">
      {messages.length === 0 ? <div className="conversation-empty"><span>✳</span><b>Session ready</b><p>Ask the agent to investigate the customer’s issue.</p></div> : messages.map(message => <div className={`message-row ${message.role}`} key={message.id}><span className={message.role === 'assistant' ? 'message-avatar ai' : 'message-avatar user'}>{message.role === 'assistant' ? '✳' : 'SD'}</span><div className="message-content"><div className="message-byline"><b>{message.role === 'assistant' ? 'Northstar AI' : 'You'}</b><time>{new Date(message.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></div><div className={`message-bubble ${message.role}`}>{message.content}</div></div></div>)}
      {execution?.proposed_action && <div className="proposal-card"><span className="proposal-icon">♧</span><div><b>Human review required</b><p>The agent identified a refund review handoff. No refund request or payment change was made. Use the Refund approvals workspace for the approval workflow.</p><Link to="/approvals">Open approvals <span>→</span></Link></div></div>}
      {execution?.status === 'failed' && <div className="inline-error">{execution.error_info || 'This run could not be completed.'}</div>}
    </div>
    <form className="composer" onSubmit={send}><label htmlFor="agent-message" className="sr-only">Message the support agent</label><textarea id="agent-message" placeholder="Write a message…" value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(e) } }} rows={2} disabled={busy || execution?.status === 'waiting_for_approval'} /><div className="composer-foot"><span>AI responses are recommendations and may need human review.</span><button className="button button-primary" type="submit" disabled={busy || !draft.trim() || execution?.status === 'waiting_for_approval'}>{busy ? 'Sending…' : 'Send message'} <span>↑</span></button></div></form>
  </div>
}

function ExecutionHistory({ ticket }: { ticket: Ticket }) {
  const [items, setItems] = useState<AgentExecution[]>([])
  const [error, setError] = useState('')
  useEffect(() => { supportApi.executions(ticket.customer_id, ticket.id).then(setItems).catch(err => setError(err.message)) }, [ticket.id])
  if (error) return <div className="muted-block">Execution history unavailable.</div>
  if (!items.length) return <div className="muted-block">No agent executions yet.</div>
  return <div className="execution-list">{items.map(item => <div className="execution-row" key={item.id}><div><b>Run #{item.id}</b><small>{new Date(item.created_at).toLocaleString()}</small></div><StatusBadge status={item.status} /></div>)}</div>
}

function ApprovalsPage() {
  const [pending, setPending] = useState<RefundApproval[]>([])
  const [selected, setSelected] = useState<RefundApproval | null>(null)
  const [historyId, setHistoryId] = useState('')
  const [result, setResult] = useState<RefundExecutionResult | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const [customer, setCustomer] = useState<Customer | null>(null)
  const [order, setOrder] = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const loadPending = async () => {
    setLoading(true); setError('')
    try { setPending(await supportApi.pendingApprovals()) }
    catch (err) { setError(err instanceof Error ? err.message : 'Approval queue could not be loaded.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void loadPending() }, [])
  const loadRelated = async (approval: RefundApproval) => {
    try {
      const authorized = await supportApi.customers()
      const candidate = await Promise.all(authorized.map(async c => {
        try { return await supportApi.ticket(approval.ticket_id, c.id) } catch { return null }
      }))
      const found = candidate.find((row): row is Ticket => row !== null)
      if (!found) return
      const owner = authorized.find(c => c.id === found.customer_id) ?? null
      setTicket(found); setCustomer(owner)
      const orderRow = await supportApi.order(approval.order_id, found.customer_id).catch(() => null)
      setOrder(orderRow)
    } catch { setTicket(null) }
  }
  const selectApproval = async (approval: RefundApproval) => { setSelected(approval); setResult(null); setError(''); setNotice(''); await loadRelated(approval) }
  const approve = async () => {
    if (!selected || !window.confirm(`Approve refund request #${selected.id} for ₹${Number(selected.requested_amount).toLocaleString('en-IN')}? This records approval; refund execution remains a separate backend workflow.`)) return
    setBusy(true); setError(''); setNotice('')
    try { const updated = await supportApi.approve(selected.id); setSelected(updated); setNotice('Approval recorded. Refund execution remains a separate authorized workflow.'); await loadPending() }
    catch (err) { setError(err instanceof Error ? err.message : 'Approval could not be recorded.') }
    finally { setBusy(false) }
  }
  const reject = async () => {
    if (!selected || !rejectReason.trim()) return
    if (!window.confirm(`Reject refund request #${selected.id}?`)) return
    setBusy(true); setError(''); setNotice('')
    try { const updated = await supportApi.reject(selected.id, rejectReason.trim()); setSelected(updated); setRejectReason(''); setNotice('Refund request rejected.'); await loadPending() }
    catch (err) { setError(err instanceof Error ? err.message : 'Rejection could not be recorded.') }
    finally { setBusy(false) }
  }
  const lookupHistory = async (event: FormEvent) => {
    event.preventDefault(); const id = Number(historyId)
    if (!Number.isInteger(id) || id < 1) { setError('Enter a valid approval ID.'); return }
    setBusy(true); setError(''); setResult(null)
    try {
      const approval = await supportApi.approval(id); setSelected(approval); await loadRelated(approval)
      if (approval.status === 'executed') setResult(await supportApi.executionResult(id))
      else setNotice(`Approval #${id} is ${approval.status}; no execution result is available.`)
    } catch (err) { setError(err instanceof Error ? err.message : 'Approval history could not be loaded.') }
    finally { setBusy(false) }
  }
  return <Shell title="Refund approvals">
    <PageTitle eyebrow="REVIEW WORKSPACE" title="Refund approvals" subtitle="Review refund requests and record a human decision." action={<button className="button button-outline" onClick={loadPending}>↻ Refresh queue</button>} />
    <div className="approval-layout">
      <Panel title="Pending review" subtitle={loading ? 'Loading queue…' : `${pending.length} request${pending.length === 1 ? '' : 's'} awaiting review`} className="approval-queue">
        {loading ? <Loading label="Loading approvals" /> : error && pending.length === 0 ? <ErrorState message={error} onRetry={loadPending} /> : pending.length === 0 ? <EmptyState title="No pending approvals" detail="New refund requests will appear here when submitted for review." /> : <div className="approval-list">{pending.map(item => <button className={`approval-list-item ${selected?.id === item.id ? 'selected' : ''}`} key={item.id} onClick={() => void selectApproval(item)}><span className="approval-list-icon">₹</span><span className="approval-list-main"><b>Refund request #{item.id}</b><small>Ticket #{item.ticket_id} · Order #{item.order_id}</small></span><span className="approval-amount">₹{Number(item.requested_amount).toLocaleString('en-IN')}</span></button>)}</div>}
      </Panel>
      <div className="approval-detail-column">
        {selected ? <Panel title={`Request #${selected.id}`} subtitle={`Submitted ${new Date(selected.created_at).toLocaleString()}`} action={<StatusBadge status={selected.status} />}>
          <div className="approval-facts"><Fact label="Ticket" value={ticket ? <Link to={`/tickets/${ticket.id}`}>#{selected.ticket_id} · {ticket.subject}</Link> : `#${selected.ticket_id}`} /><Fact label="Customer" value={customer ? <><b>{customer.name}</b><small>{customer.email}</small></> : 'Not available in the approval record'} /><Fact label="Order" value={order ? `#${order.id} · ${order.status}` : `#${selected.order_id}`} /><Fact label="Payment" value={`#${selected.payment_id} · Status not available`} /><Fact label="Requested amount" value={<strong className="amount-strong">₹{Number(selected.requested_amount).toLocaleString('en-IN')}</strong>} /><Fact label="Policy basis" value={selected.policy_basis.replaceAll('_', ' ')} /><Fact label="Request reason" value={selected.reason} /><Fact label="Requested by" value={selected.requested_by} /></div>
          <div className="policy-limitation"><span>!</span><div><b>Manual policy review is required</b><p>The backend has no item-condition or return-receipt records. Delivery windows are order-level proxies and do not verify those facts. Confirm applicable policy evidence before approving.</p></div></div>
          {selected.reviewed_by && <div className="review-record"><b>Review record</b><p>{selected.status} by {selected.reviewed_by} · {selected.reviewed_at ? new Date(selected.reviewed_at).toLocaleString() : 'time unavailable'}</p>{selected.rejection_reason && <p>Reason: {selected.rejection_reason}</p>}</div>}
          {notice && <div className="success-note">{notice}</div>}{error && <div className="inline-error">{error}</div>}
          {selected.status === 'pending' && <div className="approval-actions"><div className="reject-box"><label htmlFor="reject-reason">Rejection reason</label><textarea id="reject-reason" rows={2} placeholder="Explain why this request is rejected…" value={rejectReason} onChange={e => setRejectReason(e.target.value)} /><button className="button button-danger" disabled={busy || !rejectReason.trim()} onClick={() => void reject()}>Reject request</button></div><div className="approve-box"><p>By approving, you confirm you reviewed the policy limitations and available evidence.</p><button className="button button-primary" disabled={busy} onClick={() => void approve()}>{busy ? 'Saving…' : 'Confirm approval'}</button></div></div>}
          {result && <div className="result-card"><div className="result-heading"><span>✓</span><div><b>Refund execution confirmed</b><small>Refund #{result.refund_id} · {new Date(result.created_at).toLocaleString()}</small></div></div><div className="result-grid"><Fact label="Amount" value={`₹${Number(result.amount).toLocaleString('en-IN')}`} /><Fact label="Payment" value={`#${result.payment_id}`} /><Fact label="Status" value={<StatusBadge status={result.status} />} /><Fact label="Reason" value={result.reason} /></div></div>}
        </Panel> : <Panel title="Approval details" subtitle="Select a request to review"><EmptyState title="Choose a refund request" detail="Request details and the required policy review checklist will appear here." /></Panel>}
        <Panel title="Approval history" subtitle="Look up a known request and its execution result"><form className="history-lookup" onSubmit={lookupHistory}><label htmlFor="approval-id">Approval ID</label><input id="approval-id" inputMode="numeric" value={historyId} onChange={e => setHistoryId(e.target.value)} placeholder="e.g. 1042" /><button className="button button-outline" disabled={busy || !historyId}>Look up</button></form><p className="muted-help">The backend currently provides pending approvals and lookup by ID, but no endpoint to list all past approvals.</p></Panel>
      </div>
    </div>
  </Shell>
}

function Fact({ label, value }: { label: string; value: ReactNode }) { return <div className="fact"><span>{label}</span><div>{value}</div></div> }

function AppRoutes() {
  const navigate = useNavigate()
  return <Routes><Route path="/" element={<DashboardPage />} /><Route path="/tickets" element={<TicketsPage />} /><Route path="/tickets/:ticketId" element={<TicketDetailPage />} /><Route path="/approvals" element={<ApprovalsPage />} /><Route path="*" element={<Shell title="Not found"><PageTitle title="Page not found" subtitle="This workspace page does not exist." action={<button className="button button-primary" onClick={() => navigate('/')}>Back to overview</button>} /></Shell>} /></Routes>
}

export default function App() { return <BrowserRouter><AppRoutes /></BrowserRouter> }
