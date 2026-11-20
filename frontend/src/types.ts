export type TicketStatus = 'open' | 'in_progress' | 'resolved' | 'closed' | string
export type ExecutionStatus = 'pending' | 'running' | 'waiting_for_approval' | 'completed' | 'failed' | 'cancelled'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'executed'

export interface Customer { id: number; name: string; email: string }
export interface Ticket { id: number; customer_id: number; order_id: number | null; subject: string; description: string; status: TicketStatus }
export interface OrderItem { id: number; product_name: string; quantity: number; unit_price: number }
export interface Order { id: number; customer_id: number; status: string; items: OrderItem[] }
export interface AgentSession { id: number; ticket_id: number; customer_id: number; status: 'active' | 'closed'; created_at: string; updated_at: string }
export interface AgentMessage { id: number; session_id: number; role: 'customer' | 'assistant'; content: string; created_at: string }
export interface KnowledgeSource { id: string; document_id: string | null; document_name: string | null; category: string | null; text: string; distance: number | null }
export interface ResolutionRecommendation { ticket_id: number; issue_category: string; issue_summary: string; customer_context_summary: string; retrieved_knowledge_sources: KnowledgeSource[]; proposed_resolution: string; explanation: string; confidence_score: number; missing_information: string[]; human_review_recommended: boolean; action_required: boolean; required_action: string | null }
export interface AgentExecution { id: number; ticket_id: number; session_id: number; status: ExecutionStatus; agent_response: string | null; recommendation: ResolutionRecommendation | null; proposed_action: Record<string, unknown> | null; approval_id: number | null; error_info: string | null; created_at: string; updated_at: string }
export interface AgentConversation { session: AgentSession; messages: AgentMessage[] }
export interface AgentMessageResult { message: AgentMessage; execution: AgentExecution }
export interface SessionStatus { session: AgentSession; current_execution: AgentExecution | null }
export interface RefundApproval { id: number; ticket_id: number; order_id: number; payment_id: number; requested_amount: string; policy_basis: string; reason: string; status: ApprovalStatus; requested_by: string; policy_review_confirmed: boolean; created_at: string; reviewed_by: string | null; reviewed_at: string | null; rejection_reason: string | null; executed_at: string | null; refund_id: number | null }
export interface RefundExecutionResult { approval: RefundApproval; refund_id: number; payment_id: number; amount: string; status: string; reason: string; idempotency_key: string; created_at: string }
export interface RefundExecutionSummary { refund_id: number; amount: string; status: string; executed_at: string }
export interface RefundApprovalHistory extends RefundApproval { customer_id: number; ticket_subject: string; execution_result: RefundExecutionSummary | null }
export interface PaymentRefund { id: number; amount: string; status: string; reason: string; created_at: string }
export interface PaymentContext { id: number; amount: string; currency: string; payment_method: string; status: string; created_at: string; refunds: PaymentRefund[] }
export interface ShipmentContext { id: number; carrier: string; tracking_number: string; status: string; estimated_delivery_at: string | null; shipped_at: string | null; delivered_at: string | null }
export interface TicketContext { customer: Customer; ticket: Ticket; order: Order | null; payments: PaymentContext[]; shipments: ShipmentContext[] }

export interface AuthStatus { authenticated: boolean; user: { subject: string; name: string | null; email: string | null } | null; permissions: { reviewer: boolean; agent: boolean }; csrf_token?: string }
