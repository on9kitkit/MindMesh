/** Presentation only: never transform product, offering or entitlement IDs. */
export function mindMeshProductCopy(value: string): string {
  return value
    .replace(/\bSTUDYROOM\b/g, "MINDMESH")
    .replace(/\bStudyRoom\b/gi, "MindMesh");
}
