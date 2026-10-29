import { keyService } from '@/api/key-service'
import { useQuery } from '@tanstack/react-query'

interface ActiveChatState {
  exists: boolean
  key_name: string
}

export const useIsChatActive = () => {
  const { data: status, isLoading } = useQuery<ActiveChatState>({
    queryKey: ['is_chat_active'],
    queryFn: keyService.chatKeyExists,
    refetchOnMount: true
  })
  return {
    exists: status?.exists,
    keyName: status?.key_name,
    isLoading
  }
}
