import React from "react";
import {
  selector,
  selectorFamily,
  useRecoilCallback,
  useRecoilValue,
} from "recoil";

import Popout from "./Popout";
import { HoverItemDiv, useHighlightHover } from "./utils";
import * as atoms from "../../recoil/atoms";
import * as selectors from "../../recoil/selectors";
import * as labelAtoms from "../Filters/LabelFieldFilters.state";
import socket from "../../shared/connection";
import { packageMessage } from "../../utils/socket";

type ActionOptionProps = {
  onClick: () => void;
  text: string;
  title?: string;
  disabled?: boolean;
};

const ActionOption = ({
  onClick,
  text,
  title,
  disabled,
}: ActionOptionProps) => {
  const props = useHighlightHover(disabled);
  if (disabled) {
    return null;
  }
  return (
    <HoverItemDiv
      title={title ? title : text}
      onClick={disabled ? null : onClick}
      {...props}
    >
      {text}
    </HoverItemDiv>
  );
};

const useGridActions = (close: () => void) => {
  const clearSelection = useRecoilCallback(
    ({ snapshot, set, reset }) => async () => {
      const [oldSelected, state] = await Promise.all([
        snapshot.getPromise(atoms.selectedSamples),
        snapshot.getPromise(atoms.stateDescription),
      ]);
      oldSelected.forEach((s) => reset(atoms.isSelectedSample(s)));
      const newState = JSON.parse(JSON.stringify(state));
      newState.selected = [];
      set(atoms.stateDescription, newState);
      reset(atoms.selectedSamples);
      socket.send(packageMessage("clear_selection", {}));
      close();
    },
    [close]
  );
  const addStage = useRecoilCallback(({ snapshot, set }) => async (name) => {
    close();
    const state = await snapshot.getPromise(atoms.stateDescription);
    const newState = JSON.parse(JSON.stringify(state));
    const samples = await snapshot.getPromise(atoms.selectedSamples);
    const newView = newState.view || [];
    newView.push({
      _cls: `fiftyone.core.stages.${name}`,
      kwargs: [["sample_ids", Array.from(samples)]],
    });
    newState.view = newView;
    newState.selected = [];
    socket.send(packageMessage("update", { state: newState }));
    set(atoms.stateDescription, newState);
  });

  return [
    {
      text: "Clear selected samples",
      title: "Deselect all selected samples",
      onClick: clearSelection,
    },
    {
      text: "Only show selected samples",
      title: "Hide all other samples",
      onClick: () => addStage("Select"),
    },
    {
      text: "Hide selected samples",
      title: "Show only unselected samples",
      onClick: () => addStage("Exclude"),
    },
  ];
};

const visibleModalSampleLabels = selector<atoms.SelectedLabel[]>({
  key: "visibleModalSampleLabels",
  get: ({ get }) => {
    return get(labelAtoms.modalLabels);
  },
});

const visibleModalSampleLabelIds = selector<Set<string>>({
  key: "visibleModalSampleLabelIds",
  get: ({ get }) => {
    return new Set(
      get(visibleModalSampleLabels).map(({ label_id }) => label_id)
    );
  },
});

const visibleModalCurrentFrameLabels = selectorFamily<
  atoms.SelectedLabel[],
  number
>({
  key: "visibleModalCurrentFrameLabels",
  get: (frameNumber) => ({ get }) => {
    return get(labelAtoms.modalLabels).filter(
      ({ frame_number }) =>
        frame_number === frameNumber || typeof frame_number !== "number"
    );
  },
});

const visibleModalCurrentFrameLabelIds = selectorFamily<Set<string>, number>({
  key: "visibleModalCurrentFrameLabelIds",
  get: (frameNumber) => ({ get }) => {
    return new Set(
      get(visibleModalCurrentFrameLabels(frameNumber)).map(
        ({ label_id }) => label_id
      )
    );
  },
});

const toLabelMap = (labels: atoms.SelectedLabel[]) =>
  Object.fromEntries(labels.map(({ label_id, ...rest }) => [label_id, rest]));

const useSelectVisible = () => {
  return useRecoilCallback(({ snapshot, set }) => async () => {
    const selected = await snapshot.getPromise(selectors.selectedLabels);
    const visible = await snapshot.getPromise(visibleModalSampleLabels);
    set(selectors.selectedLabels, {
      ...selected,
      ...toLabelMap(visible),
    });
  });
};

const useUnselectVisible = () => {
  return useRecoilCallback(({ snapshot, set }) => async () => {
    const selected = await snapshot.getPromise(selectors.selectedLabels);
    const visibleIds = await snapshot.getPromise(visibleModalSampleLabelIds);

    const filtered = Object.entries(selected).filter(
      ([label_id]) => !visibleIds.has(label_id)
    );
    set(selectors.selectedLabels, Object.fromEntries(filtered));
  });
};

const useSelectVisibleFrame = (frameNumberRef) => {
  return useRecoilCallback(({ snapshot, set }) => async () => {
    const selected = await snapshot.getPromise(selectors.selectedLabels);
    const visible = await snapshot.getPromise(
      visibleModalCurrentFrameLabels(frameNumberRef.current)
    );
    set(selectors.selectedLabels, {
      ...selected,
      ...toLabelMap(visible),
    });
  });
};

const useClearSelectedLabels = () => {
  return useRecoilCallback(({ set }) => async () =>
    set(selectors.selectedLabels, {})
  );
};

const useHideSelected = () => {
  return useRecoilCallback(({ snapshot, set }) => async () => {
    const selected = await snapshot.getPromise(selectors.selectedLabels);
    const hidden = await snapshot.getPromise(atoms.hiddenLabels);
    set(selectors.selectedLabels, {});
    set(atoms.hiddenLabels, { ...hidden, ...selected });
  });
};

const useHideOthers = () => {
  return useRecoilCallback(({ snapshot, set }) => async () => {
    const selected = await snapshot.getPromise(selectors.selectedLabelIds);
    const visible = await snapshot.getPromise(visibleModalSampleLabels);
    const hidden = await snapshot.getPromise(atoms.hiddenLabels);
    set(atoms.hiddenLabels, {
      ...hidden,
      ...toLabelMap(visible.filter(({ label_id }) => !selected.has(label_id))),
    });
  });
};

const hasSetDiff = <T extends unknown>(a: Set<T>, b: Set<T>): boolean =>
  new Set([...a].filter((e) => !b.has(e))).size > 0;

const hasSetInt = <T extends unknown>(a: Set<T>, b: Set<T>): boolean =>
  new Set([...a].filter((e) => b.has(e))).size > 0;

const useModalActions = (frameNumber, close) => {
  const selectedLabels = useRecoilValue(selectors.selectedLabelIds);
  const visibleSampleLabels = useRecoilValue(visibleModalSampleLabelIds);
  const visibleFrameLabels = useRecoilValue(
    visibleModalCurrentFrameLabelIds(frameNumber)
  );
  const isVideo = useRecoilValue(selectors.isVideoDataset);
  const closeAndCall = (callback) => {
    return React.useCallback(() => {
      close();
      callback();
    }, []);
  };

  return [
    {
      text: "Select visible (current sample)",
      disabled: !hasSetDiff(visibleSampleLabels, selectedLabels),
      onClick: closeAndCall(useSelectVisible()),
    },
    {
      text: "Unselect visible (current sample)",
      disabled: !hasSetInt(selectedLabels, visibleSampleLabels),
      onClick: closeAndCall(useUnselectVisible()),
    },
    isVideo && {
      text: "Select visible (current frame)",
      disabled: !hasSetDiff(visibleFrameLabels, selectedLabels),
      onClick: closeAndCall(useSelectVisibleFrame(frameNumber)),
    },
    {
      text: "Clear selection",
      disabled: !selectedLabels.size,
      onClick: closeAndCall(useClearSelectedLabels()),
    },
    {
      text: "Hide selected",
      disabled: !selectedLabels.size,
      onClick: closeAndCall(useHideSelected()),
    },
    {
      text: "Hide others (current sample)",
      disabled: !selectedLabels.size,
      onClick: closeAndCall(useHideOthers()),
    },
  ].filter(Boolean);
};

interface SelectionActionsProps {
  modal: boolean;
  close: () => void;
  frameNumber?: number;
  bounds: any;
}

const SelectionActions = ({
  modal,
  close,
  frameNumber,
  bounds,
}: SelectionActionsProps) => {
  const actions = modal
    ? useModalActions(frameNumber, close)
    : useGridActions(close);

  return (
    <Popout modal={modal} bounds={bounds}>
      {actions.map((props, i) => (
        <ActionOption {...props} key={i} />
      ))}
    </Popout>
  );
};

export default React.memo(SelectionActions);
