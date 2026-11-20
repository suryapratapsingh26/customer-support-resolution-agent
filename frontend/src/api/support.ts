import { api } from './client'
import type { AgentConversation, AgentExecution, AgentMessageResult, AgentSession, Customer, Order, RefundApproval, RefundExecutionResult, SessionStatus, Ticket } from '../types'

const customer = (customerId: number) => ({ customerId, role: 'agent' as const })
const reviewer = { role: 'reviewer' as const }
export const supportApi = {
  customers: () => window.supportDashboardHost?.getAuthorizedCustomers() ?? Promise.reject(new Error('Secure dashboard identity integration is not connected.')),
  tickets: (customerId: number) => api.get<Ticket[]>(`/tickets/customer/${customerId}`, customer(customerId)),
  ticket: (ticketId: number, customerId: number) => api.get<Ticket>(`/tickets/${ticketId}`, customer(customerId)),
  customer: (customerId: number) => api.get<Customer>(`/customers/${customerId}`, customer(customerId)),
  orders: (customerId: number) => api.get<Order[]>(`/orders/customer/${customerId}`, customer(customerId)),
  order: (orderId: number, customerId: number) => api.get<Order>(`/orders/${orderId}`, customer(customerId)),
  createSession: (ticket: Ticket, key: string) => api.post<AgentSession>(`/customers/${ticket.customer_id}/tickets/${ticket.id}/agent-sessions`, { idempotency_key: key }, customer(ticket.customer_id)),
  sessionStatus: (customerId: number, sessionId: number) => api.get<SessionStatus>(`/customers/${customerId}/agent-sessions/${sessionId}`, customer(customerId)),
  conversation: (customerId: number, sessionId: number) => api.get<AgentConversation>(`/customers/${customerId}/agent-sessions/${sessionId}/messages`, customer(customerId)),
  sendMessage: (customerId: number, sessionId: number, content: string, key: string) => api.post<AgentMessageResult>(`/customers/${customerId}/agent-sessions/${sessionId}/messages`, { content, idempotency_key: key }, customer(customerId)),
  executions: (customerId: number, ticketId: number) => api.get<AgentExecution[]>(`/customers/${customerId}/tickets/${ticketId}/agent-executions`, customer(customerId)),
  execution: (customerId: number, executionId: number) => api.get<AgentExecution>(`/customers/${customerId}/agent-executions/${executionId}`, customer(customerId)),
  cancelExecution: (customerId: number, executionId: number) => api.post<AgentExecution>(`/customers/${customerId}/agent-executions/${executionId}/cancel`, {}, customer(customerId)),
  pendingApprovals: () => api.get<RefundApproval[]>('/refund-approvals/pending', reviewer),
  approval: (id: number) => api.get<RefundApproval>(`/refund-approvals/${id}`, reviewer),
  approve: (id: number) => api.post<RefundApproval>(`/refund-approvals/${id}/approve`, { confirm_policy_review: true }, reviewer),
  reject: (id: number, reason: string) => api.post<RefundApproval>(`/refund-approvals/${id}/reject`, { reason }, reviewer),
  executionResult: (id: number) => api.get<RefundExecutionResult>(`/refund-approvals/${id}/execution`, reviewer),
  // The frontend intentionally has no refund execution method.
}
