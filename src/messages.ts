export enum MESSAGE_TYPES {
    ERROR = 'ERROR',
    PROGRESS = 'PROGRESS',
    PROGRESS_STAGE = 'PROGRESS_STAGE',
    FETCH_METADATA_RESULT = 'FETCH_METADATA_RESULT',
}

export type ErrorMessage = {
    type: MESSAGE_TYPES.ERROR;
    error: string;
};

export type ProgressStageMessage = {
    type: MESSAGE_TYPES.PROGRESS_STAGE;
    stage: string;
};

export type FetchMetadataResult = {
    frames: number;
    distance: number;
    averageError: number;
    gpsPoints: { lat: number; lng: number }[];
    originalPoints: { lat: number; lng: number }[];
};

export type ProgressMessage = {
    type: MESSAGE_TYPES.PROGRESS;
    message: string;
};
