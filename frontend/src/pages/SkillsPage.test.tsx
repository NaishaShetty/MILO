// SkillsPage.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SkillsPage } from "./SkillsPage";
import * as skillsApi from "../api/skills";
import * as taskContext from "../state/TaskContext";
import { ApiError } from "../api/client";

vi.mock("../api/skills", async () => ({
  ...(await vi.importActual<object>("../api/skills")),
  listSkills: vi.fn(),
  editSkill: vi.fn(),
  deleteSkill: vi.fn(),
  teachSkill: vi.fn(),
}));
vi.mock("../state/TaskContext", () => ({ useTask: vi.fn() }));

const skill = (over: Partial<skillsApi.Skill> = {}): skillsApi.Skill => ({
  skill_id: "s1",
  name: "Set the table",
  wording: "set the {o0} on the {o1}",
  status: "candidate",
  successes: 2,
  failures: 1,
  success_rate: 2 / 3,
  last_used: Date.now() / 1000,
  steps: [{ action: "pickup", target: "{o0}" }, { action: "place", target: "{o0}", container: "{o1}" }],
  ...over,
});

function setup() {
  const setActiveTaskId = vi.fn();
  vi.mocked(taskContext.useTask).mockReturnValue({ setActiveTaskId } as unknown as ReturnType<typeof taskContext.useTask>);
  return setActiveTaskId;
}

describe("SkillsPage", () => {
  it("lists skills with status, success rate and last use", async () => {
    setup();
    vi.mocked(skillsApi.listSkills).mockResolvedValue([skill()]);
    render(<SkillsPage />);
    expect(await screen.findByText("Set the table")).toBeInTheDocument();
    expect(screen.getByText("learning")).toBeInTheDocument();
    expect(screen.getByText(/Say "set the … on the …"/)).toHaveTextContent("67% worked (2 of 3) · last used today");
  });

  it("renames, switches off and deletes", async () => {
    setup();
    vi.mocked(skillsApi.listSkills).mockResolvedValue([skill()]);
    vi.mocked(skillsApi.editSkill).mockResolvedValue(skill());
    vi.mocked(skillsApi.deleteSkill).mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SkillsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("New name"), { target: { value: "Lay the table" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(skillsApi.editSkill).toHaveBeenCalledWith("s1", { name: "Lay the table" }));
    fireEvent.click(screen.getByRole("button", { name: "Switch off" }));
    await waitFor(() => expect(skillsApi.editSkill).toHaveBeenCalledWith("s1", { status: "disabled" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(skillsApi.deleteSkill).toHaveBeenCalledWith("s1"));
  });

  it("teaches a skill and opens the run-back mission", async () => {
    const setActiveTaskId = setup();
    vi.mocked(skillsApi.listSkills).mockResolvedValue([]);
    vi.mocked(skillsApi.teachSkill).mockResolvedValue({
      skill: skill({ status: "teaching" }),
      task: { task_id: "t9" } as never,
      message: "Let me show you what I understood.",
    });
    render(<SkillsPage />);
    expect(await screen.findByText(/No skills yet/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Set the table" } });
    fireEvent.change(screen.getByLabelText("What you'll say"), { target: { value: "set the mug on the table" } });
    fireEvent.change(screen.getByLabelText("Steps"), { target: { value: "pick up the mug\n\nput it on the table" } });
    fireEvent.click(screen.getByRole("button", { name: "Teach" }));
    await waitFor(() =>
      expect(skillsApi.teachSkill).toHaveBeenCalledWith("Set the table", "set the mug on the table", [
        "pick up the mug",
        "put it on the table",
      ]),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Let me show you what I understood.");
    expect(setActiveTaskId).toHaveBeenCalledWith("t9");
  });

  it("shows MILO's reason when it can't learn the steps", async () => {
    setup();
    vi.mocked(skillsApi.listSkills).mockResolvedValue([]);
    vi.mocked(skillsApi.teachSkill).mockRejectedValue(
      new ApiError(400, { category: "skill", message: 'I didn\'t understand step 2: "juggle it".' }),
    );
    render(<SkillsPage />);
    await screen.findByText(/No skills yet/);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("What you'll say"), { target: { value: "x the mug" } });
    fireEvent.change(screen.getByLabelText("Steps"), { target: { value: "juggle it" } });
    fireEvent.click(screen.getByRole("button", { name: "Teach" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("step 2");
  });
});
