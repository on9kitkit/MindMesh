import type { DailyInvitation } from "../../api/learningCompanions";

/** A saved offer opens without a tap, but never over an active room. */
export function dailyOfferIsOpen(
  invitation: DailyInvitation | null,
  roomFree: boolean,
  closedStudyDate: string | null,
): boolean {
  return roomFree && invitation?.should_open === true &&
    invitation.study_date !== closedStudyDate;
}
