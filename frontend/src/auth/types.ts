// Shape of GET /api/me (the frozen backend contract).

export type ConnectionStatus =
  | 'disconnected'
  | 'connecting'
  | 'qr_pending'
  | 'connected'

export type User = {
  id: string
  email: string
  name: string
  picture: string
}

export type Business = {
  id: string
  name: string
}

export type Connection = {
  status: ConnectionStatus
}

export type Me = {
  user: User
  business: Business
  connection: Connection
  /** True only for platform operators (email ∈ server's ADMIN_EMAILS). */
  is_admin: boolean
}
