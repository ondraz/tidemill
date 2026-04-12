import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Copy } from 'lucide-react'
import { listApiKeys, createApiKey, revokeApiKey } from '@/api/apiKeys'

export function APIKeyManager() {
  const qc = useQueryClient()
  const { data: keys, isLoading } = useQuery({ queryKey: ['api-keys'], queryFn: listApiKeys })
  const create = useMutation({
    mutationFn: (name: string) => createApiKey(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })
  const revoke = useMutation({
    mutationFn: revokeApiKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })

  const [newName, setNewName] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)

  const handleCreate = async () => {
    if (!newName.trim()) return
    const result = await create.mutateAsync(newName.trim())
    setNewKey(result.key)
    setNewName('')
  }

  const copyKey = () => {
    if (newKey) {
      navigator.clipboard.writeText(newKey)
    }
  }

  if (isLoading) {
    return <div className="text-muted-foreground">Loading API keys...</div>
  }

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">API Keys</h2>
      <p className="text-sm text-muted-foreground mb-4">
        Use API keys to authenticate programmatic access to the Tidemill API.
      </p>

      {newKey && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
          <p className="text-sm font-medium text-green-800 mb-1">
            API key created. Copy it now — you won't see it again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-sm bg-white border border-green-200 rounded px-2 py-1 font-mono">
              {newKey}
            </code>
            <button
              onClick={copyKey}
              className="p-1.5 rounded hover:bg-green-100 text-green-700"
            >
              <Copy className="w-4 h-4" />
            </button>
          </div>
          <button
            onClick={() => setNewKey(null)}
            className="text-xs text-green-600 mt-2 hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="flex items-center gap-2 mb-4">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="Key name (e.g. CI Pipeline)"
          className="border border-border rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring flex-1 max-w-xs"
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
        />
        <button
          onClick={handleCreate}
          disabled={!newName.trim() || create.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" /> Create Key
        </button>
      </div>

      {!keys || keys.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground text-sm">
          No API keys yet.
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted">
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">Name</th>
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">Key</th>
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">Created</th>
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">Last Used</th>
                <th className="text-left px-4 py-2 font-medium text-muted-foreground">Status</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <tr key={key.id} className="border-t border-border">
                  <td className="px-4 py-2">{key.name}</td>
                  <td className="px-4 py-2 font-mono text-muted-foreground">{key.key_prefix}...</td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {key.created_at ? new Date(key.created_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {key.last_used_at ? new Date(key.last_used_at).toLocaleDateString() : 'Never'}
                  </td>
                  <td className="px-4 py-2">
                    {key.revoked_at ? (
                      <span className="text-xs text-destructive">Revoked</span>
                    ) : (
                      <span className="text-xs text-green-600">Active</span>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {!key.revoked_at && (
                      <button
                        onClick={() => {
                          if (confirm('Revoke this API key?')) {
                            revoke.mutate(key.id)
                          }
                        }}
                        className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
