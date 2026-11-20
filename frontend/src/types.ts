export type TicketStatus = 'open' | 'in_progress' | 'resolved' | 'closed' | string
export type ExecutionStatus = 'pending' | 'running' | 'waiting_for_approval' | 'completed' | 'failed' | 'cancelled'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'executed'

export interface Customer { id: number; name: string; email: string }
export interface Ticket { id: number; customer_id: number; order_id: number | null; subject: string; description: string; status: TicketStatus }
export interface OrderItem { id: number; product_name: string; quantity: number; unit_price: number }
export interface Order { id: number; customer_id: number; status: string; items: OrderItem[] }
export interface AgentSession { id: number; ticket_id: number; customer_id: number; status: 'active' | 'closed'; created_at: string; updated_at: string }
export interface AgentMessage { id: number; session_id: number; role: 'customer' | 'assistant'; content: string; created_at: string }
export interface AgentExecution { id: number; ticket_id: number; session_id: number; status: ExecutionStatus; agent_response: string | null; proposed_action: Record<string, unknown> | null; approval_id: number | null; error_info: string | null; created_at: string; updated_at: string }
export interface AgentConversation { session: AgentSession; messages: AgentMessage[] }
export interface AgentMessageResult { message: AgentMessage; execution: AgentExecution }
export interface SessionStatus { session: AgentSession; current_execution: AgentExecution | null }
export interface RefundApproval { id: number; ticket_id: number; order_id: number; payment_id: number; requested_amount: string; policy_basis: string; reason: string; status: ApprovalStatus; requested_by: string; policy_review_confirmed: boolean; created_at: string; reviewed_by: string | null; reviewed_at: string | null; rejection_reason: string | null; executed_at: string | null; refund_id: number | null }
export interface RefundExecutionResult { approval: RefundApproval; refund_id: number; payment_id: number; amount: string; status: string; reason: string; idempotency_key: string; created_at: string }

export interface AuthStatus { authenticated: boolean; user: { subject: string; name: string | null; email: string | null } | null; permissions: { reviewer: boolean }; csrf_token?: string }
