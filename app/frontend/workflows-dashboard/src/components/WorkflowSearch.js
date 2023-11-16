import React, { useState } from 'react';
import axios from 'axios';

const WorkflowSearch = () => {
    const [id, setId] = useState('');
    const [workflowState, setWorkflowState] = useState(null);
    const [error, setError] = useState('');

    const handleSearch = async () => {
        try {
            const response = await axios.get(`http://localhost:8000/record/${id}`);
            setWorkflowState(response.data);
            setError('');
        } catch (err) {
            setError('Workflow not found or error fetching data');
            setWorkflowState(null);
        }
    };

    return (
        <div>
            <input 
                type="text" 
                value={id} 
                onChange={(e) => setId(e.target.value)} 
                placeholder="Enter Workflow ID" 
            />
            <button onClick={handleSearch}>Search</button>
            {error && <div style={{ color: 'red' }}>{error}</div>}
            {workflowState && <div>{JSON.stringify(workflowState, null, 2)}</div>}
        </div>
    );
};

export default WorkflowSearch;
