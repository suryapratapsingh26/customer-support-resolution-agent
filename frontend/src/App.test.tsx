import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError } from './api/client'
import type { AgentConversation, AgentExecution, Customer, Order, RefundApproval, SessionStatus, Ticket } from './types'

const mocks = vi.hoisted(() => ({
  authStatus: vi.fn(), logout: vi.fn(),
  customers: vi.fn(), tickets: vi.fn(), ticket: vi.fn(), ticketContext: vi.fn(), customerApprovals: vi.fn(), createRefundApproval: vi.fn(), order: vi.fn(), createSession: vi.fn(),
  conversation: vi.fn(), sessionStatus: vi.fn(), sendMessage: vi.fn(), executions: vi.fn(), execution: vi.fn(),
  cancelExecution: vi.fn(), resumeExecution: vi.fn(), pendingApprovals: vi.fn(), approvalHistory: vi.fn(), approval: vi.fn(), approve: vi.fn(),
  reject: vi.fn(), executeRefund: vi.fn(), executionResult: vi.fn(),
}))
vi.mock('./api/support', () => ({ supportApi: mocks }))

const customer: Customer = { id: 7, name: 'Avery Chen', email: 'avery@example.test' }
const ticket: Ticket = { id: 42, customer_id: 7, order_id: 8, subject: 'Delivery has not arrived', description: 'The tracking page has not updated since Monday.', status: 'open' }
const order: Order = { id: 8, customer_id: 7, status: 'shipped', items: [{ id: 4, product_name: 'Wireless headphones', quantity: 1, unit_price: 7499 }] }
const execution: AgentExecution = { id: 21, ticket_id: 42, session_id: 13, status: 'completed', agent_response: 'Check the carrier status.', recommendation: null, proposed_action: null, approval_id: null, error_info: null, created_at: '2026-06-15T10:00:00Z', updated_at: '2026-06-15T10:01:00Z' }
const approval: RefundApproval = { id: 9, ticket_id: 42, order_id: 8, payment_id: 3, requested_amount: '1200.00', policy_basis: 'faulty_item', reason: 'Item arrived damaged.', status: 'pending', requested_by: 'intake', policy_review_confirmed: false, created_at: '2026-06-15T10:00:00Z', reviewed_by: null, reviewed_at: null, rejection_reason: null, executed_at: null, refund_id: null }

function response<T>(body: T) { return Promise.resolve(body) }
function arrange() {
  mocks.authStatus.mockImplementation(() => response({ authenticated: true, user: { subject: 'agent-1', name: 'Support Agent', email: 'agent@example.test' }, permissions: { reviewer: true, agent: true }, csrf_token: 'csrf-test' }))
  mocks.logout.mockImplementation(() => response(undefined))
  mocks.customers.mockImplementation(() => response([customer]))
  mocks.tickets.mockImplementation(() => response([ticket]))
  mocks.ticket.mockImplementation(() => response(ticket))
  mocks.ticketContext.mockImplementation(() => response({ customer, ticket, order, payments: [{ id: 3, amount: '7499.00', currency: 'INR', payment_method: 'card', status: 'success', created_at: '2026-06-15T09:00:00Z', refunds: [] }], shipments: [{ id: 5, carrier: 'Parcel Post', tracking_number: 'TRACK-5', status: 'delivered', estimated_delivery_at: null, shipped_at: '2026-06-14T09:00:00Z', delivered_at: '2026-06-15T09:00:00Z' }] }))
  mocks.customerApprovals.mockImplementation(() => response([]))
  mocks.createRefundApproval.mockImplementation(() => response(approval))
  mocks.order.mockImplementation(() => response(order))
  mocks.executions.mockImplementation(() => response([]))
  mocks.pendingApprovals.mockImplementation(() => response([approval]))
  mocks.approvalHistory.mockImplementation(() => response([{ ...approval, customer_id: customer.id, ticket_subject: ticket.subject, execution_result: null }]))
  mocks.approval.mockImplementation(() => response(approval))
  const refundResult = { approval: { ...approval, status: 'executed' as const, refund_id: 31 }, refund_id: 31, payment_id: 3, amount: '1200.00', status: 'success', reason: approval.reason, idempotency_key: 'refund-approval-9', created_at: '2026-06-15T11:00:00Z' }
  mocks.executeRefund.mockImplementation(() => response(refundResult))
  mocks.executionResult.mockImplementation(() => response(refundResult))
  mocks.resumeExecution.mockImplementation(() => response({ ...execution, status: 'completed' }))
  const session = { id: 13, ticket_id: 42, customer_id: 7, status: 'active' as const, created_at: '', updated_at: '' }
  mocks.conversation.mockImplementation(() => response({ session, messages: [] } satisfies AgentConversation))
  mocks.sessionStatus.mockImplementation(() => response({ session, current_execution: execution } satisfies SessionStatus))
}
function visit(path: string) { window.history.pushState({}, '', path); return render(<App />) }

beforeEach(() => { vi.clearAllMocks(); arrange() })
afterEach(() => { vi.restoreAllMocks(); window.history.pushState({}, '', '/') })

describe('support dashboard', () => {
  it('renders the overview from authorized customer and ticket data', async () => {
    visit('/')
    expect(await screen.findByText('Open tickets')).toBeInTheDocument()
    expect(screen.getByText('Delivery has not arrived')).toBeInTheDocument()
    expect(screen.getByText('Avery Chen')).toBeInTheDocument()
  })

  it('searches and filters the ticket queue', async () => {
    visit('/tickets')
    expect(await screen.findByText('Delivery has not arrived')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'nobody' } })
    expect(screen.getByText('No matching tickets')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'avery' } })
    expect(screen.getByText('Delivery has not arrived')).toBeInTheDocument()
  })

  it('loads ticket and order details, starts an agent session, and shows execution state', async () => {
    const existing: AgentConversation = { session: { id: 13, ticket_id: 42, customer_id: 7, status: 'active', created_at: '', updated_at: '' }, messages: [] }
    const active: SessionStatus = { session: existing.session, current_execution: execution }
    mocks.createSession.mockImplementation(() => response(existing.session))
    mocks.conversation.mockImplementation(() => response(existing))
    mocks.sessionStatus.mockImplementation(() => response(active))
    visit('/tickets/42')
    expect(await screen.findByText('Avery Chen')).toBeInTheDocument()
    expect(await screen.findByText('Wireless headphones')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Start agent session/i }))
    expect(await screen.findByText('Run #21')).toBeInTheDocument()
    expect(screen.getByText('completed')).toBeInTheDocument()
    expect(mocks.createSession).toHaveBeenCalledWith(ticket, expect.any(String))
  })

  it('shows scoped payment and shipment context and submits a human refund request', async () => {
    visit('/tickets/42')
    expect(await screen.findByText(/TRACK-5/)).toBeInTheDocument()
    expect(screen.getByText('Payment #3')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Requested amount'), { target: { value: '25.00' } })
    fireEvent.change(screen.getByLabelText('Request reason'), { target: { value: 'Customer reports damage.' } })
    fireEvent.click(screen.getByRole('button', { name: /Submit for human approval/i }))
    expect(await screen.findByText(/submitted for human review/i)).toBeInTheDocument()
    expect(mocks.createRefundApproval).toHaveBeenCalledWith(7, 42, expect.objectContaining({
      order_id: 8, payment_id: 3, requested_amount: '25.00', reason: 'Customer reports damage.',
    }))
  })

  it('shows source titles and excerpts attached to the saved recommendation', async () => {
    const session = { id: 13, ticket_id: 42, customer_id: 7, status: 'active' as const, created_at: '', updated_at: '' }
    const cited = { ...execution, recommendation: {
      ticket_id: 42, issue_category: 'shipping', issue_summary: ticket.subject,
      customer_context_summary: 'Order available.', proposed_resolution: 'Check carrier status.',
      explanation: 'Based on policy.', confidence_score: 0.8, missing_information: [],
      human_review_recommended: true, action_required: false, required_action: null,
      retrieved_knowledge_sources: [{ id: 'source-3', document_id: 'shipping-3', document_name: 'Shipping Policy', category: 'shipping', text: 'Carrier updates can take one business day.', distance: 0.12 }],
    } }
    sessionStorage.setItem('northstar-agent-session-42', '13')
    mocks.conversation.mockImplementation(() => response({ session, messages: [] }))
    mocks.sessionStatus.mockImplementation(() => response({ session, current_execution: cited }))
    visit('/tickets/42')
    expect(await screen.findByText('Shipping Policy')).toBeInTheDocument()
    expect(screen.getByText('Carrier updates can take one business day.')).toBeInTheDocument()
  })

  it('submits a message and renders the saved conversation and status', async () => {
    const session = { id: 13, ticket_id: 42, customer_id: 7, status: 'active' as const, created_at: '', updated_at: '' }
    const userMessage = { id: 4, session_id: 13, role: 'customer' as const, content: 'Can you check the shipment?', created_at: '2026-06-15T10:01:00Z' }
    const answer = { id: 5, session_id: 13, role: 'assistant' as const, content: 'The carrier status should be checked.', created_at: '2026-06-15T10:02:00Z' }
    sessionStorage.setItem('northstar-agent-session-42', '13')
    mocks.conversation.mockImplementation(() => response({ session, messages: [userMessage, answer] }))
    mocks.sessionStatus.mockImplementation(() => response({ session, current_execution: execution }))
    mocks.sendMessage.mockImplementation(() => response({ message: userMessage, execution }))
    visit('/tickets/42')
    const text = await screen.findByLabelText('Message the support agent')
    fireEvent.change(text, { target: { value: 'Can you check the shipment?' } })
    fireEvent.click(screen.getByRole('button', { name: /Send message/i }))
    expect(await screen.findByText('The carrier status should be checked.')).toBeInTheDocument()
    expect(mocks.sendMessage).toHaveBeenCalledWith(7, 13, 'Can you check the shipment?', expect.any(String))
  })

  it('reuses the same idempotency key when a message request is retried after an error', async () => {
    const session = { id: 13, ticket_id: 42, customer_id: 7, status: 'active' as const, created_at: '', updated_at: '' }
    sessionStorage.setItem('northstar-agent-session-42', '13')
    mocks.conversation.mockImplementation(() => response({ session, messages: [] }))
    mocks.sessionStatus.mockImplementation(() => response({ session, current_execution: null }))
    mocks.sendMessage.mockRejectedValueOnce(new Error('The request timed out.'))
      .mockImplementationOnce(() => response({ message: { id: 1 }, execution }))
    visit('/tickets/42')
    const composer = await screen.findByLabelText('Message the support agent')
    fireEvent.change(composer, { target: { value: 'Please check this delivery.' } })
    fireEvent.click(screen.getByRole('button', { name: /Send message/i }))
    expect(await screen.findByText('The request timed out.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Send message/i }))
    await waitFor(() => expect(mocks.sendMessage).toHaveBeenCalledTimes(2))
    const firstKey = mocks.sendMessage.mock.calls[0][3]
    const retryKey = mocks.sendMessage.mock.calls[1][3]
    expect(retryKey).toBe(firstKey)
  })

  it('loads persisted failure status after a failed execution response', async () => {
    const session = { id: 13, ticket_id: 42, customer_id: 7, status: 'active' as const, created_at: '', updated_at: '' }
    const failed = { ...execution, status: 'failed' as const, error_info: 'Agent execution failed safely.' }
    sessionStorage.setItem('northstar-agent-session-42', '13')
    mocks.conversation.mockImplementation(() => response({ session, messages: [] }))
    mocks.sessionStatus.mockImplementation(() => response({ session, current_execution: null }))
    mocks.sendMessage.mockRejectedValueOnce(new ApiError('Agent execution failed.', 503, 21))
    mocks.execution.mockImplementation(() => response(failed))
    visit('/tickets/42')
    const composer = await screen.findByLabelText('Message the support agent')
    fireEvent.change(composer, { target: { value: 'Please check this delivery.' } })
    fireEvent.click(screen.getByRole('button', { name: /Send message/i }))
    expect(await screen.findByText('Agent execution failed safely.')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()
    expect(mocks.execution).toHaveBeenCalledWith(7, 21)
  })

  it('approves a refund, explicitly executes it, and displays the verified result', async () => {
    const approved = { ...approval, status: 'approved' as const, reviewed_by: 'reviewer', policy_review_confirmed: true }
    mocks.pendingApprovals.mockImplementation(() => response([approval]))
    mocks.approve.mockImplementation(() => response(approved))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    visit('/approvals')
    fireEvent.click(await screen.findByRole('button', { name: /Refund request #9/i }))
    expect(await screen.findByText(/Manual policy review is required/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Confirm approval/i }))
    expect(await screen.findByText(/Approval recorded/i)).toBeInTheDocument()
    expect(mocks.approve).toHaveBeenCalledWith(9)
    fireEvent.click(screen.getByRole('button', { name: /Execute approved refund/i }))
    expect(await screen.findByText(/Refund execution confirmed/i)).toBeInTheDocument()
    expect(mocks.executeRefund).toHaveBeenCalledWith(9)
  })

  it('requires a rejection reason and submits it to the backend', async () => {
    const rejected = { ...approval, status: 'rejected' as const, rejection_reason: 'Outside policy.' }
    mocks.reject.mockImplementation(() => response(rejected))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    visit('/approvals')
    fireEvent.click(await screen.findByRole('button', { name: /Refund request #9/i }))
    expect(await screen.findByLabelText('Rejection reason')).toBeInTheDocument()
    const reject = screen.getByRole('button', { name: /Reject request/i })
    expect(reject).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Rejection reason'), { target: { value: 'Outside policy.' } })
    fireEvent.click(reject)
    await waitFor(() => expect(mocks.reject).toHaveBeenCalledWith(9, 'Outside policy.'))
  })

  it('looks up an executed approval and displays the backend refund result', async () => {
    const executed = { ...approval, status: 'executed' as const, refund_id: 31 }
    mocks.approval.mockImplementation(() => response(executed))
    mocks.executionResult.mockImplementation(() => response({ approval: executed, refund_id: 31, payment_id: 3, amount: '1200.00', status: 'success', reason: executed.reason, idempotency_key: 'refund-approval-9', created_at: '2026-06-15T11:00:00Z' }))
    visit('/approvals')
    fireEvent.change(await screen.findByLabelText('Approval ID'), { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }))
    expect(await screen.findByText('Refund execution confirmed')).toBeInTheDocument()
    expect(screen.getByText(/Refund #31/)).toBeInTheDocument()
    expect(mocks.executionResult).toHaveBeenCalledWith(9)
  })

  it('shows an API error state and allows a retry', async () => {
    mocks.customers.mockRejectedValueOnce(new Error('Access expired.'))
    visit('/tickets')
    expect(await screen.findByText('Access expired.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Try again/i }))
    expect(await screen.findByText('Delivery has not arrived')).toBeInTheDocument()
  })
})
