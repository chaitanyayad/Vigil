// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title IncidentAnchor
/// @notice Stores Merkle roots of VIGIL alert-event batches so the incident
///         history can be verified independently of the orchestrator's
///         database. Only 32-byte roots are stored — never metrics or alert
///         content. Not upgradeable by design (v1): an audit anchor that can
///         be swapped out defeats its own purpose.
contract IncidentAnchor {
    struct Batch {
        bytes32 root;
        uint64 firstEventId;
        uint64 lastEventId;
        uint256 timestamp;
    }

    address public owner;
    Batch[] private _batches;

    event Anchored(
        uint256 indexed batchId,
        bytes32 root,
        uint64 firstEventId,
        uint64 lastEventId,
        uint256 timestamp
    );
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    error NotOwner();
    error ZeroAddress();
    error InvalidRange();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    /// @notice Anchor a batch's Merkle root. Event ids must be sequential
    ///         across batches (append-only ledger semantics).
    function anchor(bytes32 root, uint64 firstEventId, uint64 lastEventId)
        external
        onlyOwner
        returns (uint256 batchId)
    {
        if (firstEventId > lastEventId) revert InvalidRange();
        if (_batches.length > 0) {
            // enforce forward progress: no rewriting or overlapping history
            if (firstEventId <= _batches[_batches.length - 1].lastEventId) revert InvalidRange();
        }
        batchId = _batches.length;
        _batches.push(Batch(root, firstEventId, lastEventId, block.timestamp));
        emit Anchored(batchId, root, firstEventId, lastEventId, block.timestamp);
    }

    function getBatch(uint256 id)
        external
        view
        returns (bytes32 root, uint64 firstEventId, uint64 lastEventId, uint256 timestamp)
    {
        Batch storage b = _batches[id];
        return (b.root, b.firstEventId, b.lastEventId, b.timestamp);
    }

    function batchCount() external view returns (uint256) {
        return _batches.length;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }
}
