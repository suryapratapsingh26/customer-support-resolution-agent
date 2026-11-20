import { api } from './client'
import type { AgentConversation, AgentExecution, AgentMessageResult, AgentSession, AuthStatus, Customer, Order, RefundApproval, RefundExecutionResult, SessionStatus, Ticket } from '../types'

export const supportApi = {
  authStatus: () => api.get<AuthStatus>('/auth/status'),
  customers: () => api.get<Customer[]>('/customers'),
  tickets: (customerId: number) => api.get<Ticket[]>(`/tickets/customer/${customerId}`),
  ticket: (ticketId: number, customerId: number) => api.get<Ticket>(`/customers/${customerId}/tickets/${ticketId}`),
  customer: (customerId: number) => api.get<Customer>(`/customers/${customerId}`),
  orders: (customerId: number) => api.get<Order[]>(`/orders/customer/${customerId}`),
  order: (orderId: number, customerId: number) => api.get<Order>(`/customers/${customerId}/orders/${orderId}`),
  createSession: (ticket: Ticket, key: string) => api.post<AgentSession>(`/customers/${ticket.customer_id}/tickets/${ticket.id}/agent-sessions`, { idempotency_key: key }),
  sessionStatus: (customerId: number, sessionId: number) => api.get<SessionStatus>(`/customers/${customerId}/agent-sessions/${sessionId}`),
  conversation: (customerId: number, sessionId: number) => api.get<AgentConversation>(`/customers/${customerId}/agent-sessions/${sessionId}/messages`),
  sendMessage: (customerId: number, sessionId: number, content: string, key: string) => api.post<AgentMessageResult>(`/customers/${customerId}/agent-sessions/${sessionId}/messages`, { content, idempotency_key: key }),
  executions: (customerId: number, ticketId: number) => api.get<AgentExecution[]>(`/customers/${customerId}/tickets/${ticketId}/agent-executions`),
  execution: (customerId: number, executionId: number) => api.get<AgentExecution>(`/customers/${customerId}/agent-executions/${executionId}`),
  cancelExecution: (customerId: number, executionId: number) => api.post<AgentExecution>(`/customers/${customerId}/agent-executions/${executionId}/cancel`, {}),
  pendingApprovals: () => api.get<RefundApproval[]>('/refund-approvals/pending'),
  approval: (id: number) => api.get<RefundApproval>(`/refund-approvals/${id}`),
  approve: (id: number) => api.post<RefundApproval>(`/refund-approvals/${id}/approve`, { confirm_policy_review: true }),
  reject: (id: number, reason: string) => api.post<RefundApproval>(`/refund-approvals/${id}/reject`, { reason }),
  executionResult: (id: number) => api.get<RefundExecutionResult>(`/refund-approvals/${id}/execution`),
  logout: () => api.post<void>('/auth/logout', {}),
}
