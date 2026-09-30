export type RewardDisplayStatus =
  | "not_eligible"
  | "awaiting_marking"
  | "reward_pending"
  | "credited"
  | "reward_delayed";

export function rewardStatusCopy(status: RewardDisplayStatus): string {
  switch (status) {
    case "not_eligible":
      return "This quiz did not meet the accepted-answer requirement for coins.";
    case "awaiting_marking":
      return "Written marking is still pending. No reward has been credited yet.";
    case "reward_pending":
      return "Your quiz qualified. The reward is pending server confirmation; your balance has not been increased on this screen.";
    case "credited":
      return "The server confirmed this quiz reward. A daily cap can make an additional quiz worth zero coins.";
    case "reward_delayed":
      return "The reward is delayed. Your confirmed balance is unchanged; retrying quiz marking is not a wallet repair.";
  }
}
