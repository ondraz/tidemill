interface DimensionPickerProps {
  available: string[]
  selected: string[]
  onChange: (dims: string[]) => void
}

export function DimensionPicker({ available, selected, onChange }: DimensionPickerProps) {
  const toggle = (dim: string) => {
    if (selected.includes(dim)) {
      onChange(selected.filter((d) => d !== dim))
    } else {
      onChange([...selected, dim])
    }
  }

  return (
    <div className="flex items-center gap-1 flex-wrap">
      <span className="text-xs text-muted-foreground mr-1">Group by:</span>
      {available.map((dim) => (
        <button
          key={dim}
          onClick={() => toggle(dim)}
          className={`px-2 py-0.5 text-xs rounded-full border ${
            selected.includes(dim)
              ? 'bg-primary/10 border-primary text-primary'
              : 'border-border text-muted-foreground hover:border-primary/50'
          }`}
        >
          {dim.replace(/_/g, ' ')}
        </button>
      ))}
    </div>
  )
}
