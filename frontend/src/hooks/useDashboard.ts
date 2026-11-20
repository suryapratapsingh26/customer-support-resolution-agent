import { useEffect, useState } from 'react'
import { supportApi } from '../api/support'
import { ApiError } from '../api/client'
import type { Customer, Ticket } from '../types'

export function useDashboard() {
  const [customers, setCustomers] = useState<Customer[]>([])
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const reload = async () => {
    setLoading(true)
    setError('')
    try {
      const authorizedCustomers = await supportApi.customers()
      const ticketLists = await Promise.all(authorizedCustomers.map(c => supportApi.tickets(c.id)))
      setCustomers(authorizedCustomers)
      setTickets(ticketLists.flat().sort((a, b) => b.id - a.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Dashboard data could not be loaded.')
    } finally { setLoading(false) }
  }
  useEffect(() => { void reload() }, [])
  return { customers, tickets, loading, error, reload }
}
